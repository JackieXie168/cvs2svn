#!/usr/bin/env python
# (Be in -*- python -*- mode.)
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
# This software consists of voluntary contributions made by many
# individuals.  For exact contribution history, see the revision
# history and logs, available at http://cvs2svn.tigris.org/.
# ====================================================================
#
# The purpose of verify-cvs2svn is to verify the result of a cvs2svn
# repository conversion.  The following tests are performed:
#
# 1. Content checking of the HEAD revision of trunk, all tags and all
#    branches.  Only the tags and branches in the Subversion
#    repository are checked, i.e. there are no checks to verify that
#    all tags and branches in the CVS repository are present.
#
# This program only works if you converted a subdirectory of a CVS
# repository, and not the whole repository.  If you really did convert
# a whole repository and need to check it, you must create a CVSROOT
# directory above the current root using cvs init.
#
# ====================================================================

import os
import sys
import getopt
import popen2
import shutil
import re


# CVS and Subversion command line client commands
CVS_CMD = 'cvs'
SVN_CMD = 'svn'


# Minimal, incomplete, version of popen2.Popen4 for those platforms
# for which popen2 does not provide it.
try:
  Popen4 = popen2.Popen4
except AttributeError:
  class Popen4:
    def __init__(self, cmd):
      if type(cmd) != str:
        cmd = " ".join(cmd)
      self.fromchild, self.tochild = popen2.popen4(cmd)
    def wait(self):
      return self.fromchild.close() or self.tochild.close()


class CvsRepos:
  def __init__(self, path):
    """Open the CVS repository at PATH."""
    path = os.path.abspath(path)
    if not os.path.isdir(path):
      raise RuntimeError('CVS path is not a directory')

    if os.path.exists(os.path.join(path, 'CVSROOT')):
      # The whole repository
      self.module = "."
      self.cvsroot = path
    else:
      self.cvsroot = os.path.dirname(path)
      self.module = os.path.basename(path)
      while not os.path.exists(os.path.join(self.cvsroot, 'CVSROOT')):
        parent = os.path.dirname(self.cvsroot)
        if parent == self.cvsroot:
          raise RuntimeError('Cannot find the CVSROOT')
        self.module = os.path.join(os.path.basename(self.cvsroot), self.module)
        self.cvsroot = parent

  def export(self, dest_path, rev=None):
    """Export revision REV to DEST_PATH where REV can be None to export
    the HEAD revision, or any valid CVS revision string to export that
    revision."""
    os.mkdir(dest_path)
    cmd = [ CVS_CMD, '-Q', '-d', ':local:' + self.cvsroot, 'export' ]
    if rev:
      cmd.extend([ '-r', rev ])
    else:
      cmd.extend([ '-D', 'now' ])
    cmd.extend([ '-d', dest_path, self.module ])
    pipe = Popen4(cmd)
    output = pipe.fromchild.read()
    status = pipe.wait()
    if status or output:
      print 'CMD FAILED:', ' '.join(cmd)
      print 'Output:'
      sys.stdout.write(output)
      raise RuntimeError('CVS command failed!')


class SvnRepos:
  def __init__(self, url):
    """Open the Subversion repository at URL."""
    self.url = url

    # Cache a list of all tags and branches
    list = self.list('')
    if 'tags' in list:
      self.tag_list = self.list('tags')
    else:
      self.tag_list = []
    if 'branches' in list:
      self.branch_list = self.list('branches')
    else:
      self.branch_list = []

  def export(self, path, dest_path):
    """Export PATH to DEST_PATH."""
    url = '/'.join([self.url, path])
    cmd = [ SVN_CMD, 'export', '-q', url, dest_path ]
    pipe = Popen4(cmd)
    output = pipe.fromchild.read()
    status = pipe.wait()
    if status or output:
      print 'CMD FAILED:', ' '.join(cmd)
      print 'Output:'
      sys.stdout.write(output)
      raise RuntimeError('SVN command failed!')

  def export_trunk(self, dest_path):
    """Export trunk to DEST_PATH."""
    self.export('trunk', dest_path)

  def export_tag(self, dest_path, tag):
    """Export the tag TAG to DEST_PATH."""
    self.export('tags/' + tag, dest_path)

  def export_branch(self, dest_path, branch):
    """Export the branch BRANCH to DEST_PATH."""
    self.export('branches/' + branch, dest_path)

  def list(self, path):
    """Return a list of all files and directories in PATH."""
    cmd = [ SVN_CMD, 'ls', self.url + '/' + path ]
    pipe = Popen4(cmd)
    lines = pipe.fromchild.readlines()
    status = pipe.wait()
    if status:
      print 'CMD FAILED:', ' '.join(cmd)
      print 'Output:'
      sys.stdout.writelines(lines)
      raise RuntimeError('SVN command failed!')
    entries = []
    for line in lines:
      entries.append(line[:-2])
    return entries

  def tags(self):
    """Return a list of all tags in the repository."""
    return self.tag_list

  def branches(self):
    """Return a list of all branches in the repository."""
    return self.branch_list


def transform_symbol(ctx, name):
  """Transform the symbol NAME using the renaming rules specified
  with --symbol-transform.  Return the transformed symbol name."""

  for (pattern, replacement) in ctx.symbol_transforms:
    newname = pattern.sub(replacement, name)
    if newname != name:
      print "   symbol '%s' transformed to '%s'" % (name, newname)
      name = newname

  return name


def file_compare(base1, base2, run_diff, rel_path):
  """Compare the contents of two files.  The paths are specified as two
  base paths BASE1 and BASE2, and a path REL_PATH that is relative to the
  two base paths.  Return 1 if the file contetns are identical, else 0."""
  path1 = os.path.join(base1, rel_path)
  path2 = os.path.join(base2, rel_path)
  file1 = open(path1, 'rb')
  file2 = open(path2, 'rb')
  while 1:
    data1 = file1.read(8192)
    data2 = file2.read(8192)
    if data1 != data2:
      print '*** ANOMALY: File contents differ for %s' % rel_path
      if run_diff:
        os.system('diff -u "' + path1 + '" "' + path2 + '"')
      return 0
    if len(data1) == 0:
      return 1


def tree_compare(base1, base2, run_diff, rel_path=''):
  """Compare the contents of two directory trees, including the contents
  of all files.  The paths are specified as two base paths BASE1 and BASE2,
  and a path REL_PATH that is relative to the two base paths.  Return 1
  if the trees are identical, else 0."""
  if not rel_path:
    path1 = base1
    path2 = base2
  else:
    path1 = os.path.join(base1, rel_path)
    path2 = os.path.join(base2, rel_path)
  if os.path.isfile(path1) and os.path.isfile(path2):
    return file_compare(base1, base2, run_diff, rel_path)
  if not os.path.isdir(path1) or not os.path.isdir(path2):
    print '*** ANOMALY: Path type differ for %s' % rel_path
    return 0
  entries1 = os.listdir(path1)
  entries1.sort()
  entries2 = os.listdir(path2)
  entries2.sort()
  missing = filter(lambda x: x not in entries2, entries1)
  extra = filter(lambda x: x not in entries1, entries2)
  if missing:
    print '*** ANOMALY: Directory /%s is missing entries: %s' % (
      rel_path, ', '.join(missing))
  if extra:
    print '*** ANOMALY: Directory /%s has extra entries: %s' % (
      rel_path, ', '.join(extra))
  if missing or extra:
    return 0
  ok = 1
  for entry in entries1:
    new_rel_path = os.path.join(rel_path, entry)
    if not tree_compare(base1, base2, run_diff, new_rel_path):
      ok = 0
  return ok


def verify_contents_single(cvsrepos, svnrepos, kind, label, ctx):
  """Verify that the contents of the HEAD revision of all directories
  and files in the Subversion repository SVNREPOS matches the ones in
  the CVS repository CVSREPOS.  KIND can be either 'trunk', 'tag' or
  'branch'.  If KIND is either 'tag' or 'branch', LABEL is used to
  specify the name of the tag or branch.  CTX has the attributes:
  CTX.tempdir: specifying the directory for all temporary files.
  CTX.skip_cleanup: if true, the temporary files are not deleted.
  CTX.run_diff: if true, run diff on differing files.
  """
  itemname = kind + (kind != 'trunk' and '-' + label or '')
  cvs_export_dir = os.path.join(ctx.tempdir, 'cvs-export-' + itemname)
  svn_export_dir = os.path.join(ctx.tempdir, 'svn-export-' + itemname)

  if label:
    cvslabel = transform_symbol(ctx, label)
  else:
    cvslabel = None

  try:
    cvsrepos.export(cvs_export_dir, cvslabel)
    if kind == 'trunk':
      svnrepos.export_trunk(svn_export_dir)
    elif kind == 'tag':
      svnrepos.export_tag(svn_export_dir, label)
    else:
      svnrepos.export_branch(svn_export_dir, label)

    if not tree_compare(cvs_export_dir, svn_export_dir, ctx.run_diff):
      return 0
  finally:
    if not ctx.skip_cleanup:
      if os.path.exists(cvs_export_dir):
        shutil.rmtree(cvs_export_dir)
      if os.path.exists(svn_export_dir):
        shutil.rmtree(svn_export_dir)
  return 1


def verify_contents(cvsrepos, svnrepos, ctx):
  """Verify that the contents of the HEAD revision of all directories
  and files in the trunk, all tags and all branches in the Subversion
  repository SVNREPOS matches the ones in the CVS repository CVSREPOS.
  CTX is passed through to verify_contents_single()."""
  anomalies = []

  # Verify contents of trunk
  print 'Verifying trunk'
  if not verify_contents_single(cvsrepos, svnrepos, 'trunk', None, ctx):
    anomalies.append('trunk')

  # Verify contents of all tags
  for tag in svnrepos.tags():
    print 'Verifying tag', tag
    if not verify_contents_single(cvsrepos, svnrepos, 'tag', tag, ctx):
      anomalies.append('tag:' + tag)

  # Verify contents of all branches
  for branch in svnrepos.branches():
    if branch[:10] == 'unlabeled-':
      print 'Skipped branch', branch
    else:
      print 'Verifying branch', branch
      if not verify_contents_single(cvsrepos, svnrepos, 'branch', branch, ctx):
        anomalies.append('branch:' + branch)

  # Show the results
  print
  if len(anomalies) == 0:
    print 'No content anomalies detected'
  else:
    print '%d content anomal%s detected:' % (len(anomalies),
        len(anomalies) == 1 and "y" or "ies")
    for anomaly in anomalies:
      print '   ', anomaly


class OptionContext:
  pass


def main(argv):
  def usage():
    """Print usage."""
    print 'USAGE: %s cvs-repos-path svn-repos-path' \
          % os.path.basename(argv[0])
    print '  --branch=BRANCH  verify contents of the branch BRANCH only'
    print '  --diff           run diff on differing files'
    print '  --help, -h       print this usage message and exit'
    print '  --tag=TAG        verify contents of the tag TAG only'
    print '  --tempdir=PATH   path to store temporary files'
    print '  --trunk          verify contents of trunk only'
    print '  --symbol-transform=P:S transform symbol names from P to S ' \
          'like cvs2svn,'
    print '                   except transforms SVN symbol to CVS symbol'

  def error(msg):
    """Print an error to sys.stderr."""
    sys.stderr.write('Error: ' + str(msg) + '\n')

  try:
    opts, args = getopt.getopt(
        argv[1:], 'h',
        [ 'branch=', 'diff', 'help', 'tag=', 'tempdir=',
          'trunk', 'skip-cleanup', 'symbol-transform=' ])
  except getopt.GetoptError, e:
    error(e)
    usage()
    sys.exit(1)

  # Default values
  ctx = OptionContext()
  ctx.run_diff = 0
  ctx.tempdir = ''
  ctx.skip_cleanup = 0
  ctx.symbol_transforms = []

  verify_branch = None
  verify_tag = None
  verify_trunk = None

  for opt, value in opts:
    if (opt == '--branch'):
      verify_branch = value
    elif (opt == '--diff'):
      ctx.run_diff = 1
    elif (opt == '--help') or (opt == '-h'):
      usage()
      sys.exit(0)
    elif (opt == '--tag'):
      verify_tag = value
    elif (opt == '--tempdir'):
      ctx.tempdir = value
    elif (opt == '--trunk'):
      verify_trunk = 1
    elif (opt == '--skip-cleanup'):
      ctx.skip_cleanup = 1
    elif opt == '--symbol-transform':
      # This is broken!
      [pattern, replacement] = value.split(":")
      try:
        symbol_transforms.append(
            RegexpSymbolTransform(pattern, replacement))
      except re.error:
        raise FatalError("'%s' is not a valid regexp." % (pattern,))

  # Consistency check for options and arguments.
  if len(args) != 2:
    usage()
    sys.exit(1)

  cvs_path = args[0]
  # Check if the use supplied an URL or a path
  if args[1].find('://') != -1:
    svn_url = args[1]
  else:
    abspath = os.path.abspath(args[1])
    svn_url = 'file://' + (abspath[0] != '/' and '/' or '') + abspath
    if os.sep != '/':
      svn_url = svn_url.replace(os.sep, '/')

  try:
    # Open the repositories
    cvsrepos = CvsRepos(cvs_path)
    svnrepos = SvnRepos(svn_url)

    # Do our thing...
    if verify_branch:
      print 'Verifying branch', verify_branch
      verify_contents_single(cvsrepos, svnrepos, 'branch', verify_branch, ctx)
    elif verify_tag:
      print 'Verifying tag', verify_tag
      verify_contents_single(cvsrepos, svnrepos, 'tag', verify_tag, ctx)
    elif verify_trunk:
      print 'Verifying trunk'
      verify_contents_single(cvsrepos, svnrepos, 'trunk', None, ctx)
    else:
      # Verify trunk, tags and branches
      verify_contents(cvsrepos, svnrepos, ctx)
  except RuntimeError, e:
    error(str(e))
  except KeyboardInterrupt:
    pass


if __name__ == '__main__':
  main(sys.argv)