#!/usr/bin/env python
#
#  run_tests.py:  test suite for cvs2svn
#
#  Subversion is a tool for revision control. 
#  See http://subversion.tigris.org for more information.
#    
# ====================================================================
# Copyright (c) 2000-2004 CollabNet.  All rights reserved.
#
# This software is licensed as described in the file COPYING, which
# you should have received as part of this distribution.  The terms
# are also available at http://subversion.tigris.org/license-1.html.
# If newer versions of this license are posted there, you may use a
# newer version instead, at your option.
#
######################################################################

# General modules
import sys
import shutil
import stat
import string
import re
import os
import time
import os.path
import locale

# This script needs to run in the correct directory.  Make sure we're there.
if not (os.path.exists('cvs2svn.py') and os.path.exists('test-data')):
  sys.stderr.write("error: I need to be run in the directory containing "
                   "'cvs2svn.py' and 'test-data'.\n")
  sys.exit(1)

# Load the Subversion test framework.
import svntest

# Abbreviations
Skip = svntest.testcase.Skip
XFail = svntest.testcase.XFail
Item = svntest.wc.StateItem

cvs2svn = os.path.abspath('cvs2svn.py')

# We use the installed svn and svnlook binaries, instead of using
# svntest.main.run_svn() and svntest.main.run_svnlook(), because the
# behavior -- or even existence -- of local builds shouldn't affect
# the cvs2svn test suite.
svn = 'svn'
svnlook = 'svnlook'

test_data_dir = 'test-data'
tmp_dir = 'tmp'


#----------------------------------------------------------------------
# Helpers.
#----------------------------------------------------------------------


class RunProgramException:
  pass

class MissingErrorException:
  pass

def run_program(program, error_re, *varargs):
  """Run PROGRAM with VARARGS, return stdout as a list of lines.
  If there is any stderr and ERROR_RE is None, raise
  RunProgramException, and print the stderr lines if
  svntest.main.verbose_mode is true.

  If ERROR_RE is not None, it is a string regular expression that must
  match some line of stderr.  If it fails to match, raise
  MissingErrorExpection."""
  out, err = svntest.main.run_command(program, 1, 0, *varargs)
  if err:
    if error_re:
      for line in err:
        if re.match(error_re, line):
          return out
      raise MissingErrorException
    else:
      if svntest.main.verbose_mode:
        print '\n%s said:\n' % program
        for line in err:
          print '   ' + line,
        print
      raise RunProgramException
  return out


def run_cvs2svn(error_re, *varargs):
  """Run cvs2svn with VARARGS, return stdout as a list of lines.
  If there is any stderr and ERROR_RE is None, raise
  RunProgramException, and print the stderr lines if
  svntest.main.verbose_mode is true.

  If ERROR_RE is not None, it is a string regular expression that must
  match some line of stderr.  If it fails to match, raise
  MissingErrorException."""
  if sys.platform == "win32":
    # For an unknown reason, without this special case, the cmd.exe process
    # invoked by os.system('sort ...') in cvs2svn.py receives invalid stdio
    # handles. Therefore, the redirection of the output to the .s-revs file
    # fails.
    return run_program("python", error_re, cvs2svn, *varargs)
  else:
    return run_program(cvs2svn, error_re, *varargs)


def run_svn(*varargs):
  """Run svn with VARARGS; return stdout as a list of lines.
  If there is any stderr, raise RunProgramException, and print the
  stderr lines if svntest.main.verbose_mode is true."""
  return run_program(svn, None, *varargs)


def repos_to_url(path_to_svn_repos):
  """This does what you think it does."""
  rpath = os.path.abspath(path_to_svn_repos)
  if rpath[0] != '/':
    rpath = '/' + rpath
  return 'file://%s' % string.replace(rpath, os.sep, '/')

if hasattr(time, 'strptime'):
  def svn_strptime(timestr):
    return time.strptime(timestr, '%Y-%m-%d %H:%M:%S')
else:
  # This is for Python earlier than 2.3 on Windows
  _re_rev_date = re.compile(r'(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)')
  def svn_strptime(timestr):
    matches = _re_rev_date.match(timestr).groups()
    return tuple(map(int, matches)) + (0, 1, -1)

class Log:
  def __init__(self, revision, author, date):
    self.revision = revision
    self.author = author
    
    # Internally, we represent the date as seconds since epoch (UTC).
    # Since standard subversion log output shows dates in localtime
    #
    #   "1993-06-18 00:46:07 -0500 (Fri, 18 Jun 1993)"
    #
    # and time.mktime() converts from localtime, it all works out very
    # happily.
    self.date = time.mktime(svn_strptime(date[0:19]))

    # The changed paths will be accumulated later, as log data is read.
    # Keys here are paths such as '/trunk/foo/bar', values are letter
    # codes such as 'M', 'A', and 'D'.
    self.changed_paths = { }

    # The msg will be accumulated later, as log data is read.
    self.msg = ''


def parse_log(svn_repos):
  """Return a dictionary of Logs, keyed on revision number, for SVN_REPOS."""

  class LineFeeder:
    'Make a list of lines behave like an open file handle.'
    def __init__(self, lines):
      self.lines = lines
    def readline(self):
      if len(self.lines) > 0:
        return self.lines.pop(0)
      else:
        return None

  def absorb_changed_paths(out, log):
    'Read changed paths from OUT into Log item LOG, until no more.'
    while 1:
      line = out.readline()
      if len(line) == 1: return
      line = line[:-1]
      op_portion = line[3:4]
      path_portion = line[5:]
      # # We could parse out history information, but currently we
      # # just leave it in the path portion because that's how some
      # # tests expect it.
      #
      # m = re.match("(.*) \(from /.*:[0-9]+\)", path_portion)
      # if m:
      #   path_portion = m.group(1)
      log.changed_paths[path_portion] = op_portion

  def absorb_message_body(out, num_lines, log):
    'Read NUM_LINES of log message body from OUT into Log item LOG.'
    i = 0
    while i < num_lines:
      line = out.readline()
      log.msg += line
      i += 1

  log_start_re = re.compile('^r(?P<rev>[0-9]+) \| '
                            '(?P<author>[^\|]+) \| '
                            '(?P<date>[^\|]+) '
                            '\| (?P<lines>[0-9]+) (line|lines)$')

  log_separator = '-' * 72

  logs = { }

  out = LineFeeder(run_svn('log', '-v', repos_to_url(svn_repos)))

  while 1:
    this_log = None
    line = out.readline()
    if not line: break
    line = line[:-1]

    if line.find(log_separator) == 0:
      line = out.readline()
      if not line: break
      line = line[:-1]
      m = log_start_re.match(line)
      if m:
        this_log = Log(int(m.group('rev')), m.group('author'), m.group('date'))
        line = out.readline()
        if not line.find('Changed paths:') == 0:
          print 'unexpected log output (missing changed paths)'
          print "Line: '%s'" % line
          sys.exit(1)
        absorb_changed_paths(out, this_log)
        absorb_message_body(out, int(m.group('lines')), this_log)
        logs[this_log.revision] = this_log
      elif len(line) == 0:
        break   # We've reached the end of the log output.
      else:
        print 'unexpected log output (missing revision line)'
        print "Line: '%s'" % line
        sys.exit(1)
    else:
      print 'unexpected log output (missing log separator)'
      print "Line: '%s'" % line
      sys.exit(1)
        
  return logs


def erase(path):
  """Unconditionally remove PATH and its subtree, if any.  PATH may be
  non-existent, a file or symlink, or a directory."""
  if os.path.isdir(path):
    shutil.rmtree(path)
  elif os.path.exists(path):
    os.remove(path)


def find_tag_rev(logs, tagname):
  """Search LOGS for a log message containing 'TAGNAME' and return the
  revision in which it was found."""
  for i in xrange(len(logs), 0, -1):
    if logs[i].msg.find("'"+tagname+"'") != -1:
      return i
  raise ValueError("Tag %s not found in logs" % tagname)


def sym_log_msg(symbolic_name, is_tag=None):
  """Return the expected log message for a cvs2svn-synthesized revision
  creating branch or tag SYMBOLIC_NAME."""
  # This is a copy-paste of part of cvs2svn's make_revision_props
  if is_tag:
    type = 'tag'
  else:
    type = 'branch'

  # In Python 2.2.3, we could use textwrap.fill().  Oh well :-).
  if len(symbolic_name) >= 13:
    space_or_newline = '\n'
  else:
    space_or_newline = ' '

  log = "This commit was manufactured by cvs2svn to create %s%s'%s'." \
      % (type, space_or_newline, symbolic_name)

  return log


def check_rev(logs, rev, msg, changed_paths):
  """Verify the REV of LOGS has the MSG and CHANGED_PATHS specified."""
  fail = None
  if logs[rev].msg.find(msg) != 0:
    print "Revision %d log message was:\n%s\n" % (rev, logs[rev].msg)
    print "It should have begun with:\n%s\n" % (msg,)
    fail = 1
  if logs[rev].changed_paths != changed_paths:
    print "Revision %d changed paths list was:\n%s\n" % (rev,
        logs[rev].changed_paths)
    print "It should have been:\n%s\n" % (changed_paths,)
    fail = 1
  if fail:
    raise svntest.Failure


# List of already converted names; see the NAME argument to ensure_conversion.
#
# Keys are names, values are tuples: (svn_repos, svn_wc, log_dictionary).
# The log_dictionary comes from parse_log(svn_repos).
already_converted = { }

def ensure_conversion(name, error_re=None, trunk_only=None,
                      no_prune=None, encoding=None):
  """Convert CVS repository NAME to Subversion, but only if it has not
  been converted before by this invocation of this script.  If it has
  been converted before, do nothing.

  If no error, return a tuple:

     svn_repository_path, wc_path, log_dict

  ...log_dict being the type of dictionary returned by parse_log().

  If ERROR_RE is a string, it is a regular expression expected to
  match some line of stderr printed by the conversion.  If there is an
  error and ERROR_RE is not set, then raise svntest.Failure.

  If TRUNK_ONLY is set, then pass the --trunk-only option to cvs2svn.py
  if converting NAME for the first time.

  If NO_PRUNE is set, then pass the --no-prune option to cvs2svn.py
  if converting NAME for the first time.

  NAME is just one word.  For example, 'main' would mean to convert
  './test-data/main-cvsrepos', and after the conversion, the resulting
  Subversion repository would be in './tmp/main-svnrepos', and a
  checked out head working copy in './tmp/main-wc'."""

  cvsrepos = os.path.abspath(os.path.join(test_data_dir, '%s-cvsrepos' % name))

  if not already_converted.has_key(name):

    if not os.path.isdir(tmp_dir):
      os.mkdir(tmp_dir)

    saved_wd = os.getcwd()
    try:
      os.chdir(tmp_dir)
      
      svnrepos = '%s-svnrepos' % name
      wc       = '%s-wc' % name

      # Clean up from any previous invocations of this script.
      erase(svnrepos)
      erase(wc)
      
      try:
        arg_list = [ '--bdb-txn-nosync', '-s', svnrepos, cvsrepos ]

        if no_prune:
          arg_list[:0] = [ '--no-prune' ]

        if trunk_only:
          arg_list[:0] = [ '--trunk-only' ]

        if encoding:
          arg_list[:0] = [ '--encoding=' + encoding ]

        arg_list[:0] = [ error_re ]

        ret = apply(run_cvs2svn, arg_list)
      except RunProgramException:
        raise svntest.Failure
      except MissingErrorException:
        print "Test failed because no error matched '%s'" % error_re
        raise svntest.Failure

      if not os.path.isdir(svnrepos):
        print "Repository not created: '%s'" \
              % os.path.join(os.getcwd(), svnrepos)
        raise svntest.Failure

      run_svn('co', repos_to_url(svnrepos), wc)
      log_dict = parse_log(svnrepos)
    finally:
      os.chdir(saved_wd)

    # This name is done for the rest of this session.
    already_converted[name] = (os.path.join('tmp', svnrepos),
                               os.path.join('tmp', wc),
                               log_dict)

  return already_converted[name]


#----------------------------------------------------------------------
# Tests.
#----------------------------------------------------------------------


def show_usage():
  "cvs2svn with no arguments shows usage"
  out = run_cvs2svn(None)
  if out[0].find('USAGE') < 0:
    print 'Basic cvs2svn invocation failed.'
    raise svntest.Failure


def attr_exec():
  "detection of the executable flag"
  repos, wc, logs = ensure_conversion('main')
  st = os.stat(os.path.join(wc, 'trunk', 'single-files', 'attr-exec'))
  if not st[0] & stat.S_IXUSR:
    raise svntest.Failure


def space_fname():
  "conversion of filename with a space"
  repos, wc, logs = ensure_conversion('main')
  if not os.path.exists(os.path.join(wc, 'trunk', 'single-files',
                                     'space fname')):
    raise svntest.Failure


def two_quick():
  "two commits in quick succession"
  repos, wc, logs = ensure_conversion('main')
  logs2 = parse_log(os.path.join(repos, 'trunk', 'single-files', 'twoquick'))
  if len(logs2) != 2:
    raise svntest.Failure


def prune_with_care():
  "prune, but never too much"
  # Robert Pluim encountered this lovely one while converting the
  # directory src/gnu/usr.bin/cvs/contrib/pcl-cvs/ in FreeBSD's CVS
  # repository (see issue #1302).  Step 4 is the doozy:
  #
  #   revision 1:  adds trunk/blah/, adds trunk/blah/cookie
  #   revision 2:  adds trunk/blah/NEWS
  #   revision 3:  deletes trunk/blah/cookie
  #   revision 4:  deletes blah   [re-deleting trunk/blah/cookie pruned blah!]
  #   revision 5:  does nothing
  #   
  # After fixing cvs2svn, the sequence (correctly) looks like this:
  #
  #   revision 1:  adds trunk/blah/, adds trunk/blah/cookie
  #   revision 2:  adds trunk/blah/NEWS
  #   revision 3:  deletes trunk/blah/cookie
  #   revision 4:  does nothing    [because trunk/blah/cookie already deleted]
  #   revision 5:  deletes blah
  # 
  # The difference is in 4 and 5.  In revision 4, it's not correct to
  # prune blah/, because NEWS is still in there, so revision 4 does
  # nothing now.  But when we delete NEWS in 5, that should bubble up
  # and prune blah/ instead.
  #
  # ### Note that empty revisions like 4 are probably going to become
  # ### at least optional, if not banished entirely from cvs2svn's
  # ### output.  Hmmm, or they may stick around, with an extra
  # ### revision property explaining what happened.  Need to think
  # ### about that.  In some sense, it's a bug in Subversion itself,
  # ### that such revisions don't show up in 'svn log' output.
  #
  # In the test below, 'trunk/full-prune/first' represents
  # cookie, and 'trunk/full-prune/second' represents NEWS.

  repos, wc, logs = ensure_conversion('main')

  # Confirm that revision 4 removes '/trunk/full-prune/first',
  # and that revision 6 removes '/trunk/full-prune'.
  #
  # Also confirm similar things about '/full-prune-reappear/...',
  # which is similar, except that later on it reappears, restored
  # from pruneland, because a file gets added to it.
  #
  # And finally, a similar thing for '/partial-prune/...', except that
  # in its case, a permanent file on the top level prevents the
  # pruning from going farther than the subdirectory containing first
  # and second.

  rev = 10
  for path in ('/trunk/full-prune/first',
               '/trunk/full-prune-reappear/sub/first',
               '/trunk/partial-prune/sub/first'):
    if not (logs[rev].changed_paths.get(path) == 'D'):
      print "Revision %d failed to remove '%s'." % (rev, path)
      raise svntest.Failure

  rev = 12
  for path in ('/trunk/full-prune',
               '/trunk/full-prune-reappear',
               '/trunk/partial-prune/sub'):
    if not (logs[rev].changed_paths.get(path) == 'D'):
      print "Revision %d failed to remove '%s'." % (rev, path)
      raise svntest.Failure

  rev = 47
  for path in ('/trunk/full-prune-reappear',
               '/trunk/full-prune-reappear/appears-later'):
    if not (logs[rev].changed_paths.get(path) == 'A'):
      print "Revision %d failed to create path '%s'." % (rev, path)
      raise svntest.Failure


def interleaved_commits():
  "two interleaved trunk commits, different log msgs"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  # The initial import.
  rev = 37
  for path in ('/trunk/interleaved',
               '/trunk/interleaved/1',
               '/trunk/interleaved/2',
               '/trunk/interleaved/3',
               '/trunk/interleaved/4',
               '/trunk/interleaved/5',
               '/trunk/interleaved/a',
               '/trunk/interleaved/b',
               '/trunk/interleaved/c',
               '/trunk/interleaved/d',
               '/trunk/interleaved/e',):
    if not (logs[rev].changed_paths.get(path) == 'A'):
      raise svntest.Failure

  if logs[rev].msg.find('Initial revision') != 0:
    raise svntest.Failure
    
  # This PEP explains why we pass the 'logs' parameter to these two
  # nested functions, instead of just inheriting it from the enclosing
  # scope:   http://www.python.org/peps/pep-0227.html

  def check_letters(rev, logs):
    'Return 1 if REV is the rev where only letters were committed, else None.'
    for path in ('/trunk/interleaved/a',
                 '/trunk/interleaved/b',
                 '/trunk/interleaved/c',
                 '/trunk/interleaved/d',
                 '/trunk/interleaved/e',):
      if not (logs[rev].changed_paths.get(path) == 'M'):
        return None
    if logs[rev].msg.find('Committing letters only.') != 0:
      return None
    return 1

  def check_numbers(rev, logs):
    'Return 1 if REV is the rev where only numbers were committed, else None.'
    for path in ('/trunk/interleaved/1',
                 '/trunk/interleaved/2',
                 '/trunk/interleaved/3',
                 '/trunk/interleaved/4',
                 '/trunk/interleaved/5',):
      if not (logs[rev].changed_paths.get(path) == 'M'):
        return None
    if logs[rev].msg.find('Committing numbers only.') != 0:
      return None
    return 1

  # One of the commits was letters only, the other was numbers only.
  # But they happened "simultaneously", so we don't assume anything
  # about which commit appeared first, we just try both ways.
  rev = rev + 3
  if not ((check_letters(rev, logs) and check_numbers(rev + 1, logs))
          or (check_numbers(rev, logs) and check_letters(rev + 1, logs))):
    raise svntest.Failure


def simple_commits():
  "simple trunk commits"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  # The initial import.
  rev = 22
  if not logs[rev].changed_paths == {
    '/trunk/proj': 'A',
    '/trunk/proj/default': 'A',
    '/trunk/proj/sub1': 'A',
    '/trunk/proj/sub1/default': 'A',
    '/trunk/proj/sub1/subsubA': 'A',
    '/trunk/proj/sub1/subsubA/default': 'A',
    '/trunk/proj/sub1/subsubB': 'A',
    '/trunk/proj/sub1/subsubB/default': 'A',
    '/trunk/proj/sub2': 'A',
    '/trunk/proj/sub2/default': 'A',
    '/trunk/proj/sub2/subsubA': 'A',
    '/trunk/proj/sub2/subsubA/default': 'A',
    '/trunk/proj/sub3': 'A',
    '/trunk/proj/sub3/default': 'A',
    }:
    raise svntest.Failure

  if logs[rev].msg.find('Initial revision') != 0:
    raise svntest.Failure
    
  # The first commit.
  rev = 29
  if not logs[rev].changed_paths == {
    '/trunk/proj/sub1/subsubA/default': 'M',
    '/trunk/proj/sub3/default': 'M',
    }:
    raise svntest.Failure

  if logs[rev].msg.find('First commit to proj, affecting two files.') != 0:
    raise svntest.Failure

  # The second commit.
  rev = 30
  if not logs[rev].changed_paths == {
    '/trunk/proj/default': 'M',
    '/trunk/proj/sub1/default': 'M',
    '/trunk/proj/sub1/subsubA/default': 'M',
    '/trunk/proj/sub1/subsubB/default': 'M',
    '/trunk/proj/sub2/default': 'M',
    '/trunk/proj/sub2/subsubA/default': 'M',
    '/trunk/proj/sub3/default': 'M'
    }:
    raise svntest.Failure

  if logs[rev].msg.find('Second commit to proj, affecting all 7 files.') != 0:
    raise svntest.Failure


def simple_tags():
  "simple tags and branches with no commits"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')
 
  # Verify the copy source for the tags we are about to check
  # No need to verify the copyfrom revision, as simple_commits did that
  check_rev(logs, 23, sym_log_msg('vendorbranch'), {
    '/branches/vendorbranch/proj (from /trunk/proj:22)': 'A',
    })

  fromstr = ' (from /branches/vendorbranch:24)'

  # Tag on rev 1.1.1.1 of all files in proj
  rev = find_tag_rev(logs, 'T_ALL_INITIAL_FILES')
  check_rev(logs, rev, sym_log_msg('T_ALL_INITIAL_FILES',1), {
    '/tags/T_ALL_INITIAL_FILES'+fromstr: 'A',
    '/tags/T_ALL_INITIAL_FILES/single-files': 'D',
    '/tags/T_ALL_INITIAL_FILES/partial-prune': 'D',
    })

  # The same, as a branch
  check_rev(logs, 25, sym_log_msg('B_FROM_INITIALS'), {
    '/branches/B_FROM_INITIALS'+fromstr: 'A',
    '/branches/B_FROM_INITIALS/single-files': 'D',
    '/branches/B_FROM_INITIALS/partial-prune': 'D',
    })

  # Tag on rev 1.1.1.1 of all files in proj, except one
  rev = find_tag_rev(logs, 'T_ALL_INITIAL_FILES_BUT_ONE')
  check_rev(logs, rev, sym_log_msg('T_ALL_INITIAL_FILES_BUT_ONE',1), {
    '/tags/T_ALL_INITIAL_FILES_BUT_ONE'+fromstr: 'A',
    '/tags/T_ALL_INITIAL_FILES_BUT_ONE/single-files': 'D',
    '/tags/T_ALL_INITIAL_FILES_BUT_ONE/partial-prune': 'D',
    '/tags/T_ALL_INITIAL_FILES_BUT_ONE/proj/sub1/subsubB': 'D',
    })

  # The same, as a branch
  check_rev(logs, 26, sym_log_msg('B_FROM_INITIALS_BUT_ONE'), {
    '/branches/B_FROM_INITIALS_BUT_ONE'+fromstr: 'A',
    '/branches/B_FROM_INITIALS_BUT_ONE/single-files': 'D',
    '/branches/B_FROM_INITIALS_BUT_ONE/partial-prune': 'D',
    '/branches/B_FROM_INITIALS_BUT_ONE/proj/sub1/subsubB': 'D',
    })


def simple_branch_commits():
  "simple branch commits"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  rev = 35
  if not logs[rev].changed_paths == {
    '/branches/B_MIXED/proj/default': 'M',
    '/branches/B_MIXED/proj/sub1/default': 'M',
    '/branches/B_MIXED/proj/sub2/subsubA/default': 'M',
    }:
    raise svntest.Failure

  if logs[rev].msg.find('Modify three files, on branch B_MIXED.') != 0:
    raise svntest.Failure


def mixed_time_tag():
  "mixed-time tag"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  rev = find_tag_rev(logs, 'T_MIXED')
  expected = {  
    '/tags/T_MIXED (from /trunk:30)': 'A',
    '/tags/T_MIXED/partial-prune': 'D',
    '/tags/T_MIXED/single-files': 'D',
    '/tags/T_MIXED/proj/sub2/subsubA (from /trunk/proj/sub2/subsubA:22)': 'R',
    '/tags/T_MIXED/proj/sub3 (from /trunk/proj/sub3:29)': 'R',
    }
  if rev == 15:
    expected['/tags'] = 'A'
  if not logs[rev].changed_paths == expected:
    raise svntest.Failure


def mixed_time_branch_with_added_file():
  "mixed-time branch, and a file added to the branch"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  # Empty revision, purely to store the log message of the dead 1.1 revision
  # required by the RCS file format
  # NOTE: This log message is created by CVS when the file
  # branch_B_MIXED_only is added to the branch
  check_rev(logs, 32, 'file branch_B_MIXED_only was initially added on '
      'branch B_MIXED.', {})

  # A branch from the same place as T_MIXED in the previous test,
  # plus a file added directly to the branch
  check_rev(logs, 33, sym_log_msg('B_MIXED'), {
    '/branches/B_MIXED (from /trunk:32)': 'A',
    '/branches/B_MIXED/partial-prune': 'D',
    '/branches/B_MIXED/single-files': 'D',
    '/branches/B_MIXED/proj/sub2/subsubA (from /trunk/proj/sub2/subsubA:22)':
      'R',
    '/branches/B_MIXED/proj/sub3 (from /trunk/proj/sub3:29)': 'R',
    })

  check_rev(logs, 34, 'Add a file on branch B_MIXED.', {
    '/branches/B_MIXED/proj/sub2/branch_B_MIXED_only': 'A',
    })


def mixed_commit():
  "a commit affecting both trunk and a branch"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  check_rev(logs, 36, 'A single commit affecting one file on branch B_MIXED '
      'and one on trunk.', {
    '/trunk/proj/sub2/default': 'M',
    '/branches/B_MIXED/proj/sub2/branch_B_MIXED_only': 'M',
    })


def split_time_branch():
  "branch some trunk files, and later branch the rest"
  # See test-data/main-cvsrepos/proj/README.
  repos, wc, logs = ensure_conversion('main')

  # First change on the branch, creating it
  check_rev(logs, 42, sym_log_msg('B_SPLIT'), {
    '/branches/B_SPLIT (from /trunk:36)': 'A',
    '/branches/B_SPLIT/partial-prune': 'D',
    '/branches/B_SPLIT/single-files': 'D',
    '/branches/B_SPLIT/proj/sub1/subsubB': 'D',
    })

  check_rev(logs, 43, 'First change on branch B_SPLIT.', {
    '/branches/B_SPLIT/proj/default': 'M',
    '/branches/B_SPLIT/proj/sub1/default': 'M',
    '/branches/B_SPLIT/proj/sub1/subsubA/default': 'M',
    '/branches/B_SPLIT/proj/sub2/default': 'M',
    '/branches/B_SPLIT/proj/sub2/subsubA/default': 'M',
    })

  # A trunk commit for the file which was not branched
  check_rev(logs, 44, 'A trunk change to sub1/subsubB/default.  '
      'This was committed about an', {
    '/trunk/proj/sub1/subsubB/default': 'M',
    })

  # Add the file not already branched to the branch, with modification:w
  check_rev(logs, 45, sym_log_msg('B_SPLIT'), {
    '/branches/B_SPLIT/proj/sub1/subsubB (from /trunk/proj/sub1/subsubB:44)': 'A',
    })

  check_rev(logs, 46, 'This change affects sub3/default and '
      'sub1/subsubB/default, on branch', {
    '/branches/B_SPLIT/proj/sub1/subsubB/default': 'M',
    '/branches/B_SPLIT/proj/sub3/default': 'M',
    })


def bogus_tag():
  "conversion of invalid symbolic names"
  ret, ign, ign = ensure_conversion('bogus-tag')


def overlapping_branch():
  "ignore a file with a branch with two names"
  repos, wc, logs = ensure_conversion('overlapping-branch',
                                      '.*cannot also have name \'vendorB\'')
  nonlap_path = '/trunk/nonoverlapping-branch'
  lap_path = '/trunk/overlapping-branch'
  if not (logs[3].changed_paths.get('/branches/vendorA (from /trunk:2)')
          == 'A'):
    raise svntest.Failure
  # We don't know what order the first two commits would be in, since
  # they have different log messages but the same timestamps.  As only
  # one of the files would be on the vendorB branch in the regression
  # case being tested here, we allow for either order.
  if ((logs[3].changed_paths.get('/branches/vendorB (from /trunk:1)')
       == 'A')
      or (logs[3].changed_paths.get('/branches/vendorB (from /trunk:2)')
          == 'A')):
    raise svntest.Failure
  if not logs[4].changed_paths == {}:
    raise svntest.Failure
  if len(logs) != 4:
    raise svntest.Failure


def phoenix_branch():
  "convert a branch file rooted in a 'dead' revision"
  repos, wc, logs = ensure_conversion('phoenix')
  check_rev(logs, 6, sym_log_msg('volsung_20010721'), {
    '/branches/volsung_20010721 (from /trunk:5)': 'A'
    })
  check_rev(logs, 7, 'This file was supplied by Jack Moffitt', {
    '/branches/volsung_20010721/phoenix': 'A' })


def ctrl_char_in_log():
  "handle a control char in a log message"
  # This was issue #1106.
  repos, wc, logs = ensure_conversion('ctrl-char-in-log')
  if not ((logs[1].changed_paths.get('/trunk') == 'A')
          and (logs[1].changed_paths.get('/trunk/ctrl-char-in-log') == 'A')
          and (len(logs[1].changed_paths) == 2)):
    print "Revision 1 of 'ctrl-char-in-log,v' was not converted successfully."
    raise svntest.Failure
  if logs[1].msg.find('\x04') < 0:
    print "Log message of 'ctrl-char-in-log,v' (rev 1) is wrong."
    raise svntest.Failure


def overdead():
  "handle tags rooted in a redeleted revision"
  repos, wc, logs = ensure_conversion('overdead')


def no_trunk_prune():
  "ensure that trunk doesn't get pruned"
  repos, wc, logs = ensure_conversion('overdead')
  for rev in logs.keys():
    rev_logs = logs[rev]
    for changed_path in rev_logs.changed_paths.keys():
      if changed_path == '/trunk' \
         and rev_logs.changed_paths[changed_path] == 'D':
        raise svntest.Failure


def double_delete():
  "file deleted twice, in the root of the repository"
  # This really tests several things: how we handle a file that's
  # removed (state 'dead') in two successive revisions; how we
  # handle a file in the root of the repository (there were some
  # bugs in cvs2svn's svn path construction for top-level files); and
  # the --no-prune option.
  repos, wc, logs = ensure_conversion('double-delete', None, 1, 1)
  
  path = '/trunk/twice-removed'

  if not (logs[1].changed_paths.get(path) == 'A'):
    raise svntest.Failure

  if logs[1].msg.find('Initial revision') != 0:
    raise svntest.Failure

  if not (logs[2].changed_paths.get(path) == 'D'):
    raise svntest.Failure

  if logs[2].msg.find('Remove this file for the first time.') != 0:
    raise svntest.Failure

  if logs[2].changed_paths.has_key('/trunk'):
    raise svntest.Failure


def split_branch():
  "branch created from both trunk and another branch"
  # See test-data/split-branch-cvsrepos/README.
  #
  # The conversion will fail if the bug is present, and
  # ensure_conversion would raise svntest.Failure.
  repos, wc, logs = ensure_conversion('split-branch')
  

def resync_misgroups():
  "resyncing should not misorder commit groups"
  # See test-data/resync-misgroups-cvsrepos/README.
  #
  # The conversion will fail if the bug is present, and
  # ensure_conversion would raise svntest.Failure.
  repos, wc, logs = ensure_conversion('resync-misgroups')
  

def tagged_branch_and_trunk():
  "allow tags with mixed trunk and branch sources"
  repos, wc, logs = ensure_conversion('tagged-branch-n-trunk')
  a_path = os.path.join(wc, 'tags', 'some-tag', 'a.txt')
  b_path = os.path.join(wc, 'tags', 'some-tag', 'b.txt')
  if not (os.path.exists(a_path) and os.path.exists(b_path)):
    raise svntest.Failure
  if (open(a_path, 'r').read().find('1.24') == -1) \
     or (open(b_path, 'r').read().find('1.5') == -1):
    raise svntest.Failure
  

def enroot_race():
  "never use the rev-in-progress as a copy source"
  # See issue #1427 and r8544.
  repos, wc, logs = ensure_conversion('enroot-race')
  if not logs[7].changed_paths == {
    '/branches/mybranch (from /trunk:6)': 'A',
    '/branches/mybranch/proj/a.txt': 'D',
    '/branches/mybranch/proj/b.txt': 'D',
    }:
    raise svntest.Failure
  if not logs[8].changed_paths == {
    '/branches/mybranch/proj/c.txt': 'M',
    '/trunk/proj/a.txt': 'M',
    '/trunk/proj/b.txt': 'M',
    }:
    raise svntest.Failure


def enroot_race_obo():
  "do use the last completed rev as a copy source"
  repos, wc, logs = ensure_conversion('enroot-race-obo')
  if not ((len(logs) == 2) and
      (logs[2].changed_paths.get('/branches/BRANCH (from /trunk:1)') == 'A')):
    raise svntest.Failure


def branch_delete_first():
  "correctly handle deletion as initial branch action"
  # See test-data/branch-delete-first-cvsrepos/README.
  #
  # The conversion will fail if the bug is present, and
  # ensure_conversion would raise svntest.Failure.
  repos, wc, logs = ensure_conversion('branch-delete-first')

  # 'file' was deleted from branch-1 and branch-2, but not branch-3
  if os.path.exists(os.path.join(wc, 'branches', 'branch-1', 'file')):
    raise svntest.Failure
  if os.path.exists(os.path.join(wc, 'branches', 'branch-2', 'file')):
    raise svntest.Failure
  if not os.path.exists(os.path.join(wc, 'branches', 'branch-3', 'file')):
    raise svntest.Failure

  
def nonascii_filenames():
  "non ascii files converted incorrectly"
  # see issue #1255

  # on a en_US.iso-8859-1 machine this test fails with
  # svn: Can't recode ...
  #
  # as described in the issue

  # on a en_US.UTF-8 machine this test fails with
  # svn: Malformed XML ...
  #
  # which means at least it fails. Unfortunately it won't fail
  # with the same error...

  # mangle current locale settings so we know we're not running
  # a UTF-8 locale (which does not exhibit this problem)
  current_locale = locale.getlocale()
  new_locale = 'en_US.ISO8859-1'
  locale_changed = None

  try:
    # change locale to non-UTF-8 locale to generate latin1 names
    locale.setlocale(locale.LC_ALL, # this might be too broad?
                     new_locale)
    locale_changed = 1
  except locale.Error:
    raise svntest.Skip

  try:
    testdata_path = os.path.abspath('test-data')
    srcrepos_path = os.path.join(testdata_path,'main-cvsrepos')
    dstrepos_path = os.path.join(testdata_path,'non-ascii-cvsrepos')
    if not os.path.exists(dstrepos_path):
      # create repos from existing main repos
      shutil.copytree(srcrepos_path, dstrepos_path)
      base_path = os.path.join(dstrepos_path, 'single-files')
      shutil.copyfile(os.path.join(base_path, 'twoquick,v'),
                      os.path.join(base_path, 'two\366uick,v'))
      new_path = os.path.join(dstrepos_path, 'single\366files')
      os.rename(base_path, new_path)

    # if ensure_conversion can generate a 
    repos, wc, logs = ensure_conversion('non-ascii', encoding='latin1')
  finally:
    if locale_changed:
      locale.setlocale(locale.LC_ALL, current_locale)
    shutil.rmtree(dstrepos_path)
    

def vendor_branch_sameness():
  "avoid spurious changes for initial revs "
  repos, wc, logs = ensure_conversion('vendor-branch-sameness')

  # There are four files in the repository:
  #
  #    a.txt: Imported in the traditional way; 1.1 and 1.1.1.1 have
  #           the same contents, the file's default branch is 1.1.1,
  #           and both revisions are in state 'Exp'.
  #
  #    b.txt: Like a.txt, except that 1.1.1.1 has a real change from
  #           1.1 (the addition of a line of text).
  #
  #    c.txt: Like a.txt, except that 1.1.1.1 is in state 'dead'.
  #
  #    d.txt: This file was created by 'cvs add' instead of import, so
  #           it has only 1.1 -- no 1.1.1.1, and no default branch.
  #           The timestamp on the add is exactly the same as for the
  #           imports of the other files.
  #
  # (Log messages for the same revisions are the same in all files.)
  #
  # What we expect to see is everyone added in r1, then trunk/proj
  # copied in r2.  In the copy, only a.txt should be left untouched;
  # b.txt should be 'M'odified, and (for different reasons) c.txt and
  # d.txt should be 'D'eleted.

  if logs[1].msg.find('Initial revision') != 0:
    raise svntest.Failure

  if not logs[1].changed_paths == {
    '/trunk' : 'A',
    '/trunk/proj' : 'A',
    '/trunk/proj/a.txt' : 'A',
    '/trunk/proj/b.txt' : 'A',
    '/trunk/proj/c.txt' : 'A',
    '/trunk/proj/d.txt' : 'A',
    }:
    raise svntest.Failure

  if logs[2].msg.find(sym_log_msg('vbranchA')) != 0:
    raise svntest.Failure

  if not logs[2].changed_paths == {
    '/branches' : 'A',
    '/branches/vbranchA (from /trunk:1)' : 'A',
    '/branches/vbranchA/proj/d.txt' : 'D',
    }:
    raise svntest.Failure

  if logs[3].msg.find('First vendor branch revision.') != 0:
    raise svntest.Failure

  if not logs[3].changed_paths == {
    '/branches/vbranchA/proj/b.txt' : 'M',
    '/branches/vbranchA/proj/c.txt' : 'D',
    }:
    raise svntest.Failure


def default_branches():
  "handle default branches correctly "
  repos, wc, logs = ensure_conversion('default-branches')

  # There are seven files in the repository:
  #
  #    a.txt:
  #       Imported in the traditional way, so 1.1 and 1.1.1.1 are the
  #       same.  Then 1.1.1.2 and 1.1.1.3 were imported, then 1.2
  #       committed (thus losing the default branch "1.1.1"), then
  #       1.1.1.4 was imported.  All vendor import release tags are
  #       still present.
  #
  #    b.txt:
  #       Like a.txt, but without rev 1.2.
  #
  #    c.txt:
  #       Exactly like b.txt, just s/b.txt/c.txt/ in content.
  #
  #    d.txt:
  #       Same as the previous two, but 1.1.1 branch is unlabeled.
  #
  #    e.txt:
  #       Same, but missing 1.1.1 label and all tags but 1.1.1.3.
  #
  #    deleted-on-vendor-branch.txt,v:
  #       Like b.txt and c.txt, except that 1.1.1.3 is state 'dead'. 
  # 
  #    added-then-imported.txt,v:
  #       Added with 'cvs add' to create 1.1, then imported with
  #       completely different contents to create 1.1.1.1, therefore
  #       never had a default branch.
  #

  check_rev(logs, 17, sym_log_msg('vtag-4',1), {
    '/tags/vtag-4 (from /branches/vbranchA:12)' : 'A',
    '/tags/vtag-4/proj/d.txt '
    '(from /branches/unlabeled-1.1.1/proj/d.txt:12)' : 'A',
    })

  check_rev(logs, 16, sym_log_msg('vtag-1',1), {
    '/tags/vtag-1 (from /branches/vbranchA:4)' : 'A',
    '/tags/vtag-1/proj/d.txt '
    '(from /branches/unlabeled-1.1.1/proj/d.txt:4)' : 'A',
    })

  check_rev(logs, 15, sym_log_msg('vtag-2',1), {
    '/tags/vtag-2 (from /branches/vbranchA:5)' : 'A',
    '/tags/vtag-2/proj/d.txt '
    '(from /branches/unlabeled-1.1.1/proj/d.txt:5)' : 'A',
    })

  check_rev(logs, 14, sym_log_msg('vtag-3',1), {
    '/tags' : 'A',
    '/tags/vtag-3 (from /branches/vbranchA:7)' : 'A',
    '/tags/vtag-3/proj/d.txt '
    '(from /branches/unlabeled-1.1.1/proj/d.txt:7)' : 'A',
    '/tags/vtag-3/proj/e.txt '
    '(from /branches/unlabeled-1.1.1/proj/e.txt:7)' : 'A',
    })

  check_rev(logs, 13, "This commit was generated by cvs2svn "
                       "to compensate for changes in r12,", {
    '/trunk/proj/b.txt (from /branches/vbranchA/proj/b.txt:12)' : 'R',
    '/trunk/proj/c.txt (from /branches/vbranchA/proj/c.txt:12)' : 'R',
    '/trunk/proj/d.txt (from /branches/unlabeled-1.1.1/proj/d.txt:12)' : 'R',
    '/trunk/proj/deleted-on-vendor-branch.txt '
    '(from /branches/vbranchA/proj/deleted-on-vendor-branch.txt:12)' : 'A',
    '/trunk/proj/e.txt (from /branches/unlabeled-1.1.1/proj/e.txt:12)' : 'R',
    })
  
  check_rev(logs, 12, "Import (vbranchA, vtag-4).", {
    '/branches/unlabeled-1.1.1/proj/d.txt' : 'M',
    '/branches/unlabeled-1.1.1/proj/e.txt' : 'M',
    '/branches/vbranchA/proj/a.txt' : 'M',
    '/branches/vbranchA/proj/added-then-imported.txt': 'M', # CHECK!!!
    '/branches/vbranchA/proj/b.txt' : 'M',
    '/branches/vbranchA/proj/c.txt' : 'M',
    '/branches/vbranchA/proj/deleted-on-vendor-branch.txt' : 'A',
    })

  check_rev(logs, 11, sym_log_msg('vbranchA'), {
    '/branches/vbranchA/proj/added-then-imported.txt '
    '(from /trunk/proj/added-then-imported.txt:10)' : 'A',
    })

  check_rev(logs, 10, "Add a file to the working copy.", {
    '/trunk/proj/added-then-imported.txt' : 'A',
    })

  check_rev(logs, 9, "First regular commit, to a.txt, on vtag-3.", {
    '/trunk/proj/a.txt' : 'M',
    })

  check_rev(logs, 8, "This commit was generated by cvs2svn "
                      "to compensate for changes in r7,", {
    '/trunk/proj/a.txt (from /branches/vbranchA/proj/a.txt:7)' : 'R',
    '/trunk/proj/b.txt (from /branches/vbranchA/proj/b.txt:7)' : 'R',
    '/trunk/proj/c.txt (from /branches/vbranchA/proj/c.txt:7)' : 'R',
    '/trunk/proj/d.txt (from /branches/unlabeled-1.1.1/proj/d.txt:7)' : 'R',
    '/trunk/proj/deleted-on-vendor-branch.txt' : 'D',
    '/trunk/proj/e.txt (from /branches/unlabeled-1.1.1/proj/e.txt:7)' : 'R',
    })

  check_rev(logs, 7, "Import (vbranchA, vtag-3).", {
    '/branches/unlabeled-1.1.1/proj/d.txt' : 'M',
    '/branches/unlabeled-1.1.1/proj/e.txt' : 'M',
    '/branches/vbranchA/proj/a.txt' : 'M',
    '/branches/vbranchA/proj/b.txt' : 'M',
    '/branches/vbranchA/proj/c.txt' : 'M',
    '/branches/vbranchA/proj/deleted-on-vendor-branch.txt' : 'D',
    })

  check_rev(logs, 6, "This commit was generated by cvs2svn "
                      "to compensate for changes in r5,", {
    '/trunk/proj/a.txt (from /branches/vbranchA/proj/a.txt:5)' : 'R',
    '/trunk/proj/b.txt (from /branches/vbranchA/proj/b.txt:5)' : 'R',
    '/trunk/proj/c.txt (from /branches/vbranchA/proj/c.txt:5)' : 'R',
    '/trunk/proj/d.txt (from /branches/unlabeled-1.1.1/proj/d.txt:5)' : 'R',
    '/trunk/proj/deleted-on-vendor-branch.txt '
    '(from /branches/vbranchA/proj/deleted-on-vendor-branch.txt:5)' : 'R',
    '/trunk/proj/e.txt (from /branches/unlabeled-1.1.1/proj/e.txt:5)' : 'R',
    })

  check_rev(logs, 5, "Import (vbranchA, vtag-2).", {
    '/branches/unlabeled-1.1.1/proj/d.txt' : 'M',
    '/branches/unlabeled-1.1.1/proj/e.txt' : 'M',
    '/branches/vbranchA/proj/a.txt' : 'M',
    '/branches/vbranchA/proj/b.txt' : 'M',
    '/branches/vbranchA/proj/c.txt' : 'M',
    '/branches/vbranchA/proj/deleted-on-vendor-branch.txt' : 'M',
    })

  check_rev(logs, 4, "Import (vbranchA, vtag-1).", {}) 
                     
  check_rev(logs, 3, sym_log_msg('vbranchA'), {
    '/branches/vbranchA (from /trunk:1)' : 'A',
    '/branches/vbranchA/proj/d.txt' : 'D',
    '/branches/vbranchA/proj/e.txt' : 'D',
    })

  check_rev(logs, 2, sym_log_msg('unlabeled-1.1.1'), {
    '/branches' : 'A',
    '/branches/unlabeled-1.1.1 (from /trunk:1)' : 'A',
    '/branches/unlabeled-1.1.1/proj/a.txt' : 'D',
    '/branches/unlabeled-1.1.1/proj/b.txt' : 'D',
    '/branches/unlabeled-1.1.1/proj/c.txt' : 'D',
    '/branches/unlabeled-1.1.1/proj/deleted-on-vendor-branch.txt' : 'D',
    })

  check_rev(logs, 1, "Initial revision", {
    '/trunk' : 'A',
    '/trunk/proj' : 'A',
    '/trunk/proj/a.txt' : 'A',
    '/trunk/proj/b.txt' : 'A',
    '/trunk/proj/c.txt' : 'A',
    '/trunk/proj/d.txt' : 'A',
    '/trunk/proj/deleted-on-vendor-branch.txt' : 'A',
    '/trunk/proj/e.txt' : 'A',
    })


def compose_tag_three_sources():
  "compose a tag from three sources"
  repos, wc, logs = ensure_conversion('compose-tag-three-sources')

  check_rev(logs, 1, "Add on trunk", {
    '/trunk': 'A',
    '/trunk/tagged-on-trunk-1.2-a': 'A',
    '/trunk/tagged-on-trunk-1.2-b': 'A',
    '/trunk/tagged-on-trunk-1.1': 'A',
    '/trunk/tagged-on-b1': 'A',
    '/trunk/tagged-on-b2': 'A',
    })

  check_rev(logs, 2, sym_log_msg('b1'), {
    '/branches': 'A',
    '/branches/b1 (from /trunk:1)': 'A',
    })

  check_rev(logs, 3, "Commit on branch b1", {
    '/branches/b1/tagged-on-trunk-1.2-a': 'M',
    '/branches/b1/tagged-on-trunk-1.2-b': 'M',
    '/branches/b1/tagged-on-trunk-1.1': 'M',
    '/branches/b1/tagged-on-b1': 'M',
    '/branches/b1/tagged-on-b2': 'M',
    })

  check_rev(logs, 4, sym_log_msg('b2'), {
    '/branches/b2 (from /trunk:1)': 'A',
    })

  check_rev(logs, 5, "Commit on branch b2", {
    '/branches/b2/tagged-on-trunk-1.2-a': 'M',
    '/branches/b2/tagged-on-trunk-1.2-b': 'M',
    '/branches/b2/tagged-on-trunk-1.1': 'M',
    '/branches/b2/tagged-on-b1': 'M',
    '/branches/b2/tagged-on-b2': 'M',
    })

  check_rev(logs, 6, "Commit again on trunk", {
    '/trunk/tagged-on-trunk-1.2-a': 'M',
    '/trunk/tagged-on-trunk-1.2-b': 'M',
    '/trunk/tagged-on-trunk-1.1': 'M',
    '/trunk/tagged-on-b1': 'M',
    '/trunk/tagged-on-b2': 'M',
    })

  check_rev(logs, 7, sym_log_msg('T',1), {
    '/tags': 'A',
    '/tags/T (from /trunk:6)': 'A',
    '/tags/T/tagged-on-b1 (from /branches/b1/tagged-on-b1:3)': 'R',
    '/tags/T/tagged-on-b2 (from /branches/b2/tagged-on-b2:5)': 'R',
    '/tags/T/tagged-on-trunk-1.1 (from /trunk/tagged-on-trunk-1.1:1)': 'R',
    })


#----------------------------------------------------------------------

########################################################################
# Run the tests

# list all tests here, starting with None:
test_list = [ None,
              show_usage,
              attr_exec,
              space_fname,
              two_quick,
              prune_with_care,
              interleaved_commits,
              simple_commits,
              simple_tags,
              simple_branch_commits,
              mixed_time_tag,
              mixed_time_branch_with_added_file,
              mixed_commit,
              split_time_branch,
              bogus_tag,
              overlapping_branch,
              phoenix_branch,
              ctrl_char_in_log,
              overdead,
              no_trunk_prune,
              double_delete,
              split_branch,
              resync_misgroups,
              tagged_branch_and_trunk,
              enroot_race,
              enroot_race_obo,
              branch_delete_first,
              nonascii_filenames,
              vendor_branch_sameness,
              default_branches,
              compose_tag_three_sources,
             ]

if __name__ == '__main__':
  svntest.main.run_tests(test_list)
  # NOTREACHED


### End of file.
