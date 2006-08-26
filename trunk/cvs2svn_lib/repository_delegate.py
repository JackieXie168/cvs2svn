# (Be in -*- python -*- mode.)
#
# ====================================================================
# Copyright (c) 2000-2006 CollabNet.  All rights reserved.
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

"""This module contains class RepositoryDelegate."""


import os

from cvs2svn_lib.boolean import *
from cvs2svn_lib.common import CommandError
from cvs2svn_lib.common import FatalError
from cvs2svn_lib.context import Ctx
from cvs2svn_lib.log import Log
from cvs2svn_lib.process import SimplePopen
from cvs2svn_lib.process import run_command
from cvs2svn_lib.dumpfile_delegate import DumpfileDelegate


class RepositoryDelegate(DumpfileDelegate):
  """Creates a new Subversion Repository.  DumpfileDelegate does all
  of the heavy lifting."""

  def __init__(self):
    self.svnadmin = Ctx().svnadmin
    self.target = Ctx().target
    if not Ctx().existing_svnrepos:
      Log().normal("Creating new repository '%s'" % (self.target))
      if not Ctx().fs_type:
        # User didn't say what kind repository (bdb, fsfs, etc).
        # We still pass --bdb-txn-nosync.  It's a no-op if the default
        # repository type doesn't support it, but we definitely want
        # it if BDB is the default.
        run_command('%s create %s "%s"' % (self.svnadmin,
                                           "--bdb-txn-nosync",
                                           self.target))
      elif Ctx().fs_type == 'bdb':
        # User explicitly specified bdb.
        #
        # Since this is a BDB repository, pass --bdb-txn-nosync,
        # because it gives us a 4-5x speed boost (if cvs2svn is
        # creating the repository, cvs2svn should be the only program
        # accessing the svn repository (until cvs is done, at least)).
        # But we'll turn no-sync off in self.finish(), unless
        # instructed otherwise.
        run_command('%s create %s %s "%s"' % (self.svnadmin,
                                              "--fs-type=bdb",
                                              "--bdb-txn-nosync",
                                              self.target))
      else:
        # User specified something other than bdb.
        run_command('%s create %s "%s"' % (self.svnadmin,
                                           "--fs-type=%s" % Ctx().fs_type,
                                           self.target))

    # Since the output of this run is a repository, not a dumpfile,
    # the temporary dumpfiles we create should go in the tmpdir.  But
    # since we delete it ourselves, we don't want to use
    # artifact_manager.
    DumpfileDelegate.__init__(self, Ctx().get_temp_filename(Ctx().dumpfile))

    self.dumpfile = open(self.dumpfile_path, 'w+b')
    self.loader_pipe = SimplePopen([ self.svnadmin, 'load', '-q',
                                     self.target ], True)
    self.loader_pipe.stdout.close()
    try:
      self._write_dumpfile_header(self.loader_pipe.stdin)
    except IOError:
      raise FatalError("svnadmin failed with the following output while "
                       "loading the dumpfile:\n"
                       + self.loader_pipe.stderr.read())

  def start_commit(self, revnum, revprops):
    """Start a new commit."""

    DumpfileDelegate.start_commit(self, revnum, revprops)

  def end_commit(self):
    """Feed the revision stored in the dumpfile to the svnadmin load pipe."""

    DumpfileDelegate.end_commit(self)

    self.dumpfile.seek(0)
    while True:
      data = self.dumpfile.read(128*1024) # Chunk size is arbitrary
      if not data:
        break
      try:
        self.loader_pipe.stdin.write(data)
      except IOError:
        raise FatalError("svnadmin failed with the following output "
                         "while loading the dumpfile:\n"
                         + self.loader_pipe.stderr.read())
    self.dumpfile.seek(0)
    self.dumpfile.truncate()

  def finish(self):
    """Clean up."""

    self.dumpfile.close()
    self.loader_pipe.stdin.close()
    error_output = self.loader_pipe.stderr.read()
    exit_status = self.loader_pipe.wait()
    if exit_status:
      raise CommandError('svnadmin load', exit_status, error_output)
    os.remove(self.dumpfile_path)

    # If this is a BDB repository, and we created the repository, and
    # --bdb-no-sync wasn't passed, then comment out the DB_TXN_NOSYNC
    # line in the DB_CONFIG file, because txn syncing should be on by
    # default in BDB repositories.
    #
    # We determine if this is a BDB repository by looking for the
    # DB_CONFIG file, which doesn't exist in FSFS, rather than by
    # checking Ctx().fs_type.  That way this code will Do The Right
    # Thing in all circumstances.
    db_config = os.path.join(self.target, "db/DB_CONFIG")
    if (not Ctx().existing_svnrepos and not Ctx().bdb_txn_nosync
        and os.path.exists(db_config)):
      no_sync = 'set_flags DB_TXN_NOSYNC\n'

      contents = open(db_config, 'r').readlines()
      index = contents.index(no_sync)
      contents[index] = '# ' + no_sync
      contents = open(db_config, 'w').writelines(contents)


