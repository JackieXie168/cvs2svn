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

"""This module contains class PersistenceManager."""

import bisect

from cvs2svn_lib.boolean import *
from cvs2svn_lib import config
from cvs2svn_lib.common import clean_symbolic_name
from cvs2svn_lib.common import SVN_INVALID_REVNUM
from cvs2svn_lib.log import Log
from cvs2svn_lib.context import Ctx
from cvs2svn_lib.artifact_manager import artifact_manager
from cvs2svn_lib.database import Database
from cvs2svn_lib.database import DB_OPEN_NEW
from cvs2svn_lib.database import DB_OPEN_READ
from cvs2svn_lib.cvs_item_database import CVSItemDatabase
from cvs2svn_lib.symbol_database import TagSymbol
from cvs2svn_lib.symbol_database import SymbolDatabase
from cvs2svn_lib.metadata_database import MetadataDatabase
from cvs2svn_lib.svn_commit import SVNCommit


class PersistenceManager:
  """The PersistenceManager allows us to effectively store SVNCommits
  to disk and retrieve them later using only their subversion revision
  number as the key.  It also returns the subversion revision number
  for a given CVSRevision's unique key.

  All information pertinent to each SVNCommit is stored in a series of
  on-disk databases so that SVNCommits can be retrieved on-demand.

  MODE is one of the constants DB_OPEN_NEW or DB_OPEN_READ.
  In 'new' mode, PersistenceManager will initialize a new set of on-disk
  databases and be fully-featured.
  In 'read' mode, PersistenceManager will open existing on-disk databases
  and the set_* methods will be unavailable."""

  def __init__(self, mode):
    self.mode = mode
    if mode not in (DB_OPEN_NEW, DB_OPEN_READ):
      raise RuntimeError, "Invalid 'mode' argument to PersistenceManager"
    self.svn2cvs_db = Database(
        artifact_manager.get_temp_file(config.SVN_REVNUMS_TO_CVS_REVS), mode)
    self.cvs2svn_db = Database(
        artifact_manager.get_temp_file(config.CVS_REVS_TO_SVN_REVNUMS), mode)
    self.svn_commit_metadata = MetadataDatabase(DB_OPEN_READ)
    self._cvs_items_db = CVSItemDatabase(
        artifact_manager.get_temp_file(config.CVS_ITEMS_RESYNC_DB),
        DB_OPEN_READ)
    if not Ctx().trunk_only:
      self.symbol_db = SymbolDatabase(DB_OPEN_READ)

    # "branch_name" -> [svn_revnums in which branch was filled].
    self._fills = {}

  def last_filled(self, name):
    """Return the last Subversion revision number in which NAME was filled.
    This is used by CVSCommit._pre_commit, to prevent creating a fill
    revision which would have nothing to do."""

    return self._fills.get(name, [None])[-1]

  def first_fill_after(self, name, revnum):
    """Return the Subversion revision number of the first fill of
    NAME after REVNUM, or None if NAME had no fills after REVNUM."""

    fills = self._fills.get(name)
    if not fills:
      return None

    i = bisect.bisect_right(fills, revnum)
    if i == len(fills):
      return None

    return fills[i]

  def get_svn_revnum(self, cvs_rev_id):
    """Return the Subversion revision number in which CVS_REV_ID was
    committed, or SVN_INVALID_REVNUM if there is no mapping for
    CVS_REV_ID."""

    return int(self.cvs2svn_db.get('%x' % (cvs_rev_id,), SVN_INVALID_REVNUM))

  def get_svn_commit(self, svn_revnum):
    """Return an SVNCommit that corresponds to SVN_REVNUM.

    If no SVNCommit exists for revnum SVN_REVNUM, then return None.

    This method can throw SVNCommitInternalInconsistencyError."""

    svn_commit = SVNCommit("Retrieved from disk", svn_revnum)
    (c_rev_keys, motivating_revnum, name, date) = self.svn2cvs_db.get(
        str(svn_revnum), (None, None, None, None))
    if c_rev_keys is None:
      return None

    metadata_id = None
    for key in c_rev_keys:
      c_rev_id = int(key, 16)
      c_rev = self._cvs_items_db[c_rev_id]
      svn_commit.add_revision(c_rev)
      # Set the author and log message for this commit by using
      # CVSRevision metadata, but only if haven't done so already.
      if metadata_id is None:
        metadata_id = c_rev.metadata_id
        author, log_msg = self.svn_commit_metadata[metadata_id]
        svn_commit.set_author(author)
        svn_commit.set_log_msg(log_msg)

    svn_commit.set_date(date)

    # If we're doing a trunk-only conversion, we don't need to do any more
    # work.
    if Ctx().trunk_only:
      return svn_commit

    if name:
      if svn_commit.cvs_revs:
        raise SVNCommit.SVNCommitInternalInconsistencyError(
            "An SVNCommit cannot have CVSRevisions *and* a corresponding\n"
            "symbolic name ('%s') to fill."
            % (clean_symbolic_name(name),))
      svn_commit.set_symbolic_name(name)
      symbol = self.symbol_db.get_symbol(name)
      if isinstance(symbol, TagSymbol):
        svn_commit.is_tag = 1

    if motivating_revnum is not None:
      svn_commit.set_motivating_revnum(motivating_revnum)

    return svn_commit

  def put_svn_commit(self, svn_revnum, cvs_revs,
                     date, name, motivating_revnum):
    """Record the bidirectional mapping between SVN_REVNUM and
    CVS_REVS and record associated attributes."""

    if self.mode == DB_OPEN_READ:
      raise RuntimeError, \
          'Write operation attempted on read-only PersistenceManager'

    for c_rev in cvs_revs:
      Log().verbose(" %x" % (c_rev.id,))

    self.svn2cvs_db[str(svn_revnum)] = (
        ['%x' % (x.id,) for x in cvs_revs], motivating_revnum, name, date)

    for c_rev in cvs_revs:
      self.cvs2svn_db['%x' % (c_rev.id,)] = svn_revnum

    # If it is not a primary commit, then record _fills.  name is
    # allowed to be None (but why bother filling _fills in that
    # case?).
    if name or motivating_revnum:
      self._fills.setdefault(name, []).append(svn_revnum)


