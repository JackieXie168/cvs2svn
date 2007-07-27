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

"""This module contains database facilities used by cvs2svn."""


from cvs2svn_lib.boolean import *
from cvs2svn_lib import config
from cvs2svn_lib.common import OP_DELETE
from cvs2svn_lib.context import Ctx
from cvs2svn_lib.artifact_manager import artifact_manager
from cvs2svn_lib.database import DB_OPEN_READ
from cvs2svn_lib.line_of_development import Branch
from cvs2svn_lib.svn_revision_range import SVNRevisionRange


# Constants used in SYMBOL_OPENINGS_CLOSINGS
OPENING = 'O'
CLOSING = 'C'


class SymbolingsLogger:
  """Manage the file that contains lines for symbol openings and closings.

  This data will later be used to determine valid SVNRevision ranges
  from which a file can be copied when creating a branch or tag in
  Subversion.  Do this by finding "Openings" and "Closings" for each
  file copied onto a branch or tag.

  An "Opening" is the CVSRevision from which a given branch/tag
  sprouts on a path.

  The "Closing" for that branch/tag and path is the next CVSRevision
  on the same line of development as the opening.

  For example, on file 'foo.c', branch BEE has branch number 1.2.2 and
  obviously sprouts from revision 1.2.  Therefore, 1.2 is the opening
  for BEE on path 'foo.c', and 1.3 is the closing for BEE on path
  'foo.c'.  Note that there may be many revisions chronologically
  between 1.2 and 1.3, for example, revisions on branches of 'foo.c',
  perhaps even including on branch BEE itself.  But 1.3 is the next
  revision *on the same line* as 1.2, that is why it is the closing
  revision for those symbolic names of which 1.2 is the opening.

  The reason for doing all this hullabaloo is to make branch and tag
  creation as efficient as possible by minimizing the number of copies
  and deletes per creation.  For example, revisions 1.2 and 1.3 of
  foo.c might correspond to revisions 17 and 30 in Subversion.  That
  means that when creating branch BEE, there is some motivation to do
  the copy from one of 17-30.  Now if there were another file,
  'bar.c', whose opening and closing CVSRevisions for BEE corresponded
  to revisions 24 and 39 in Subversion, we would know that the ideal
  thing would be to copy the branch from somewhere between 24 and 29,
  inclusive.
  """

  def __init__(self):
    self.symbolings = open(
        artifact_manager.get_temp_file(config.SYMBOL_OPENINGS_CLOSINGS), 'w')

    # This keys of this dictionary are *source* cvs_paths for which
    # we've encountered an 'opening' on the default branch.  The
    # values are the ids of symbols that this path has opened.
    self._open_paths_with_default_branches = { }

  def log_revision(self, cvs_rev, svn_revnum):
    """Log any openings and closings found in CVS_REV."""

    if isinstance(cvs_rev.lod, Branch):
      branch_id = cvs_rev.lod.symbol.id
    else:
      branch_id = None

    for symbol_id in cvs_rev.tag_ids + cvs_rev.branch_ids:
      self._note_default_branch_opening(cvs_rev, symbol_id)
      if cvs_rev.op != OP_DELETE:
        self._log(symbol_id, svn_revnum, cvs_rev.cvs_file, branch_id, OPENING)

    for symbol_id in cvs_rev.closed_symbol_ids:
      self._log(symbol_id, svn_revnum, cvs_rev.cvs_file, branch_id, CLOSING)

  def _log(self, symbol_id, svn_revnum, cvs_file, branch_id, type):
    """Log an opening or closing to self.symbolings.

    Write out a single line to the symbol_openings_closings file
    representing that SVN_REVNUM of SVN_FILE on BRANCH_ID is either
    the opening or closing (TYPE) of NAME (a symbolic name).

    TYPE should be one of the following constants: OPENING or CLOSING.

    BRANCH_ID is the symbol id of the branch on which the opening or
    closing occurred, or None if the opening/closing occurred on the
    default branch."""

    if branch_id is None:
      branch_id = '*'
    else:
      branch_id = '%x' % branch_id
    self.symbolings.write(
        '%x %d %s %s %x\n'
        % (symbol_id, svn_revnum, type, branch_id, cvs_file.id))

  def close(self):
    self.symbolings.close()

  def _note_default_branch_opening(self, cvs_rev, symbol_id):
    """If CVS_REV is a default branch revision, log CVS_REV.cvs_path
    as an opening for SYMBOLIC_NAME."""

    self._open_paths_with_default_branches.setdefault(
        cvs_rev.cvs_path, []).append(symbol_id)

  def log_default_branch_closing(self, cvs_rev, svn_revnum):
    """If self._open_paths_with_default_branches contains
    CVS_REV.cvs_path, then call log each symbol in
    self._open_paths_with_default_branches[CVS_REV.cvs_path] as a
    closing with SVN_REVNUM as the closing revision number."""

    path = cvs_rev.cvs_path
    if path in self._open_paths_with_default_branches:
      # log each symbol as a closing
      for symbol_id in self._open_paths_with_default_branches[path]:
        self._log(symbol_id, svn_revnum, cvs_rev.cvs_file, None, CLOSING)
      # Remove them from the openings list as we're done with them.
      del self._open_paths_with_default_branches[path]


class OpeningsClosingsMap:
  """A dictionary of openings and closings for a symbol in the current
  SVNCommit.

  The user should call self.register() for the openings and closings,
  then self.get_node_tree() to retrieve the information as a
  SymbolFillingGuide."""

  def __init__(self, symbol):
    """Initialize OpeningsClosingsMap and prepare it for receiving
    openings and closings."""

    self.symbol = symbol

    # A dictionary of SVN_PATHS to SVNRevisionRange objects.
    self.things = { }

  def register(self, svn_path, svn_revnum, type):
    """Register an opening or closing revision for this symbolic name.
    SVN_PATH is the source path that needs to be copied into
    self.symbol, and SVN_REVNUM is either the first svn revision
    number that we can copy from (our opening), or the last (not
    inclusive) svn revision number that we can copy from (our
    closing).  TYPE indicates whether this path is an opening or a a
    closing.

    The opening for a given SVN_PATH must be passed before the closing
    for it to have any effect... any closing encountered before a
    corresponding opening will be discarded.

    It is not necessary to pass a corresponding closing for every
    opening."""

    # Always log an OPENING
    if type == OPENING:
      self.things[svn_path] = SVNRevisionRange(svn_revnum)
    # Only log a closing if we've already registered the opening for that
    # path.
    elif type == CLOSING and svn_path in self.things:
      self.things[svn_path].add_closing(svn_revnum)

  def is_empty(self):
    """Return true if we haven't accumulated any openings or closings,
    false otherwise."""

    return not len(self.things)

  def get_things(self):
    """Return a list of (svn_path, SVNRevisionRange) tuples for all
    svn_paths with registered openings or closings."""

    return self.things.items()

