# (Be in -*- python -*- mode.)
#
# ====================================================================
# Copyright (c) 2000-2007 CollabNet.  All rights reserved.
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

"""This module contains database facilities used by cvs2svn."""


from __future__ import generators

import cPickle

from cvs2svn_lib.boolean import *
from cvs2svn_lib import config
from cvs2svn_lib.common import DB_OPEN_READ
from cvs2svn_lib.common import DB_OPEN_WRITE
from cvs2svn_lib.common import DB_OPEN_NEW
from cvs2svn_lib.log import Log
from cvs2svn_lib.artifact_manager import artifact_manager
from cvs2svn_lib.cvs_file import CVSPath


class CVSFileDatabase:
  """A Database to store CVSFile objects and retrieve them by their id."""

  def __init__(self, mode):
    """Initialize an instance, opening database in MODE (like the MODE
    argument to Database or anydbm.open())."""

    self.mode = mode

    if self.mode == DB_OPEN_NEW:
      # A list of CVSFile instances where _cvs_files[cvs_file.id] ==
      # cvs_file.  If there are any gaps in the numerical sequence,
      # the corresponding array positions are None.
      self._cvs_files = []
    elif self.mode == DB_OPEN_READ:
      f = open(artifact_manager.get_temp_file(config.CVS_FILES_DB), 'rb')
      self._cvs_files = cPickle.load(f)
      f.close()
    else:
      raise RuntimeError('Invalid mode %r' % self.mode)

  def log_file(self, cvs_file):
    """Add CVS_FILE, a CVSFile instance, to the database."""

    if self.mode == DB_OPEN_READ:
      raise RuntimeError('Cannot write items in mode %r' % self.mode)

    # Extend array if necessary:
    while cvs_file.id >= len(self._cvs_files):
      self._cvs_files.append(None)

    self._cvs_files[cvs_file.id] = cvs_file

  def itervalues(self):
    for cvs_file in self._cvs_files:
      if cvs_file is not None:
        yield cvs_file

  def get_file(self, id):
    """Return the CVSFile with the specified ID."""

    retval = self._cvs_files[id]
    if retval is None:
      raise KeyError(id)
    return retval

  def close(self):
    if self.mode == DB_OPEN_NEW:
      f = open(artifact_manager.get_temp_file(config.CVS_FILES_DB), 'wb')
      cPickle.dump(self._cvs_files, f, -1)
      f.close()

    self._cvs_files = None

