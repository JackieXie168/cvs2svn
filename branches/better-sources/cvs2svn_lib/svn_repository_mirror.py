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

"""This module contains the SVNRepositoryMirror class."""


from cvs2svn_lib.boolean import *
from cvs2svn_lib import config
from cvs2svn_lib.common import clean_symbolic_name
from cvs2svn_lib.common import path_join
from cvs2svn_lib.common import path_split
from cvs2svn_lib.common import OP_ADD
from cvs2svn_lib.common import OP_CHANGE
from cvs2svn_lib.common import OP_DELETE
from cvs2svn_lib.context import Ctx
from cvs2svn_lib.log import Log
from cvs2svn_lib.key_generator import KeyGenerator
from cvs2svn_lib.artifact_manager import artifact_manager
from cvs2svn_lib.database import Database
from cvs2svn_lib.database import SDatabase
from cvs2svn_lib.database import DB_OPEN_NEW
from cvs2svn_lib.database import DB_OPEN_READ
from cvs2svn_lib.symbol_database import TagSymbol
from cvs2svn_lib.symbol_database import SymbolDatabase
from cvs2svn_lib.symbolings_reader import SymbolingsReader
from cvs2svn_lib.fill_source import FillSource
from cvs2svn_lib.svn_revision_range import SVNRevisionRange
from cvs2svn_lib.svn_commit_item import SVNCommitItem
from cvs2svn_lib.svn_commit import SVNCommit


class SVNRepositoryMirror:
  """Mirror a Subversion Repository as it is constructed, one
  SVNCommit at a time.  The mirror is skeletal; it does not contain
  file contents.  The creation of a dumpfile or Subversion repository
  is handled by delegates.  See self.add_delegate method for how to
  set delegates.

  The structure of the repository is kept in two databases and one
  hash.  The revs_db database maps revisions to root node keys, and
  the nodes_db database maps node keys to nodes.  A node is a hash
  from directory names to keys.  Both the revs_db and the nodes_db are
  stored on disk and each access is expensive.

  The nodes_db database only has the keys for old revisions.  The
  revision that is being contructed is kept in memory in the new_nodes
  hash which is cheap to access.

  You must invoke _start_commit between SVNCommits.

  *** WARNING *** All path arguments to methods in this class CANNOT
      have leading or trailing slashes."""

  class SVNRepositoryMirrorPathExistsError(Exception):
    """Exception raised if an attempt is made to add a path to the
    repository mirror and that path already exists in the youngest
    revision of the repository."""

    pass

  class SVNRepositoryMirrorUnexpectedOperationError(Exception):
    """Exception raised if a CVSRevision is found to have an unexpected
    operation (OP) value."""

    pass

  class SVNRepositoryMirrorInvalidFillOperationError(Exception):
    """Exception raised if an empty SymbolicNameFillingGuide is returned
    during a fill where the branch in question already exists."""

    pass

  def __init__(self):
    """Set up the SVNRepositoryMirror and prepare it for SVNCommits."""

    self.key_generator = KeyGenerator()

    self.delegates = [ ]

    # This corresponds to the 'revisions' table in a Subversion fs.
    self.revs_db = SDatabase(
        artifact_manager.get_temp_file(config.SVN_MIRROR_REVISIONS_DB),
        DB_OPEN_NEW)

    # This corresponds to the 'nodes' table in a Subversion fs.  (We
    # don't need a 'representations' or 'strings' table because we
    # only track metadata, not file contents.)
    self.nodes_db = Database(
        artifact_manager.get_temp_file(config.SVN_MIRROR_NODES_DB),
        DB_OPEN_NEW)

    # Start at revision 0 without a root node.  It will be created
    # by _open_writable_root_node.
    self.youngest = 0
    self.new_root_key = None
    self.new_nodes = { }

    if not Ctx().trunk_only:
      self.symbol_db = SymbolDatabase(DB_OPEN_READ)
      self.symbolings_reader = SymbolingsReader()

  def _initialize_repository(self, date):
    """Initialize the repository by creating the directories for
    trunk, tags, and branches.  This method should only be called
    after all delegates are added to the repository mirror."""

    # Make a 'fake' SVNCommit so we can take advantage of the revprops
    # magic therein
    svn_commit = SVNCommit("Initialization", 1)
    svn_commit.set_date(date)
    svn_commit.set_log_msg("New repository initialized by cvs2svn.")

    self._start_commit(svn_commit)
    self._mkdir(Ctx().project.trunk_path)
    if not Ctx().trunk_only:
      self._mkdir(Ctx().project.branches_path)
      self._mkdir(Ctx().project.tags_path)

  def _start_commit(self, svn_commit):
    """Start a new commit."""

    if self.youngest > 0:
      self._end_commit()

    self.youngest = svn_commit.revnum
    self.new_root_key = None
    self.new_nodes = { }

    self._invoke_delegates('start_commit', svn_commit)

  def _end_commit(self):
    """Called at the end of each commit.  This method copies the newly
    created nodes to the on-disk nodes db."""

    if self.new_root_key is None:
      # No changes were made in this revision, so we make the root node
      # of the new revision be the same as the last one.
      self.revs_db[str(self.youngest)] = self.revs_db[str(self.youngest - 1)]
    else:
      self.revs_db[str(self.youngest)] = self.new_root_key
      # Copy the new nodes to the nodes_db
      for key, value in self.new_nodes.items():
        self.nodes_db[key] = value

  def _get_node(self, key):
    """Returns the node contents for KEY which may refer to either
    self.nodes_db or self.new_nodes."""

    if self.new_nodes.has_key(key):
      return self.new_nodes[key]
    else:
      return self.nodes_db[key]

  def _open_readonly_node(self, path, revnum):
    """Open a readonly node for PATH at revision REVNUM.  Returns the
    node key and node contents if the path exists, else (None, None)."""

    # Get the root key
    if revnum == self.youngest:
      if self.new_root_key is None:
        node_key = self.revs_db[str(self.youngest - 1)]
      else:
        node_key = self.new_root_key
    else:
      node_key = self.revs_db[str(revnum)]

    for component in path.split('/'):
      node_contents = self._get_node(node_key)
      node_key = node_contents.get(component, None)
      if node_key is None:
        return None

    return node_key

  def _open_writable_root_node(self):
    """Open a writable root node.  The current root node is returned
    immeditely if it is already writable.  If not, create a new one by
    copying the contents of the root node of the previous version."""

    if self.new_root_key is not None:
      return self.new_root_key, self.new_nodes[self.new_root_key]

    if self.youngest < 2:
      new_contents = { }
    else:
      new_contents = self.nodes_db[self.revs_db[str(self.youngest - 1)]]
    self.new_root_key = self.key_generator.gen_key()
    self.new_nodes = { self.new_root_key: new_contents }

    return self.new_root_key, new_contents

  def _open_writable_node(self, svn_path, create):
    """Open a writable node for the path SVN_PATH, creating SVN_PATH
    and any missing directories if CREATE is True."""

    parent_key, parent_contents = self._open_writable_root_node()

    # Walk up the path, one node at a time.
    path_so_far = None
    components = svn_path.split('/')
    for i in range(len(components)):
      component = components[i]
      path_so_far = path_join(path_so_far, component)
      this_key = parent_contents.get(component, None)
      if this_key is not None:
        # The component exists.
        this_contents = self.new_nodes.get(this_key, None)
        if this_contents is None:
          # Suck the node from the nodes_db, but update the key
          this_contents = self.nodes_db[this_key]
          this_key = self.key_generator.gen_key()
          self.new_nodes[this_key] = this_contents
          parent_contents[component] = this_key
      elif create:
        # The component does not exists, so we create it.
        this_contents = { }
        this_key = self.key_generator.gen_key()
        self.new_nodes[this_key] = this_contents
        parent_contents[component] = this_key
        if i < len(components) - 1:
          self._invoke_delegates('mkdir', path_so_far)
      else:
        # The component does not exists and we are not instructed to
        # create it, so we give up.
        return None, None

      parent_key = this_key
      parent_contents = this_contents

    return this_key, this_contents

  def _path_exists(self, path):
    """If PATH exists in self.youngest of the svn repository mirror,
    return true, else return None.

    PATH must not start with '/'."""

    return self._open_readonly_node(path, self.youngest) is not None

  def _fast_delete_path(self, parent_path, parent_contents, component):
    """Delete COMPONENT from the parent direcory PARENT_PATH with the
    contents PARENT_CONTENTS.  Do nothing if COMPONENT does not exist
    in PARENT_CONTENTS."""

    if parent_contents.has_key(component):
      del parent_contents[component]
      self._invoke_delegates('delete_path',
                             path_join(parent_path, component))

  def _delete_path(self, svn_path, should_prune=False):
    """Delete PATH from the tree.  If SHOULD_PRUNE is true, then delete
    all ancestor directories that are made empty when SVN_PATH is deleted.
    In other words, SHOULD_PRUNE is like the -P option to 'cvs checkout'.

    NOTE: This function ignores requests to delete the root directory
    or any directory for which Ctx().project.is_unremovable() returns
    True, either directly or by pruning."""

    if svn_path == '' or Ctx().project.is_unremovable(svn_path):
      return

    (parent_path, entry,) = path_split(svn_path)
    if parent_path:
      parent_key, parent_contents = \
          self._open_writable_node(parent_path, False)
    else:
      parent_key, parent_contents = self._open_writable_root_node()

    if parent_key is not None:
      self._fast_delete_path(parent_path, parent_contents, entry)
      # The following recursion makes pruning an O(n^2) operation in the
      # worst case (where n is the depth of SVN_PATH), but the worst case
      # is probably rare, and the constant cost is pretty low.  Another
      # drawback is that we issue a delete for each path and not just
      # a single delete for the topmost directory pruned.
      if should_prune and len(parent_contents) == 0:
        self._delete_path(parent_path, True)

  def _mkdir(self, path):
    """Create PATH in the repository mirror at the youngest revision."""

    self._open_writable_node(path, True)
    self._invoke_delegates('mkdir', path)

  def _change_path(self, cvs_rev):
    """Register a change in self.youngest for the CVS_REV's svn_path
    in the repository mirror."""

    # We do not have to update the nodes because our mirror is only
    # concerned with the presence or absence of paths, and a file
    # content change does not cause any path changes.
    self._invoke_delegates('change_path', SVNCommitItem(cvs_rev, False))

  def _add_path(self, cvs_rev):
    """Add the CVS_REV's svn_path to the repository mirror."""

    self._open_writable_node(cvs_rev.svn_path, True)
    self._invoke_delegates('add_path', SVNCommitItem(cvs_rev, True))

  def _copy_path(self, src_path, dest_path, src_revnum):
    """Copy SRC_PATH at subversion revision number SRC_REVNUM to
    DEST_PATH. In the youngest revision of the repository, DEST_PATH's
    parent *must* exist, but DEST_PATH *cannot* exist.

    Return the node key and the contents of the new node at DEST_PATH
    as a dictionary."""

    # get the contents of the node of our src_path
    src_key = self._open_readonly_node(src_path, src_revnum)
    src_contents = self._get_node(src_key)

    # Get the parent path and the base path of the dest_path
    (dest_parent, dest_basename,) = path_split(dest_path)
    dest_parent_key, dest_parent_contents = \
                   self._open_writable_node(dest_parent, False)

    if dest_parent_contents.has_key(dest_basename):
      msg = "Attempt to add path '%s' to repository mirror " % dest_path
      msg += "when it already exists in the mirror."
      raise self.SVNRepositoryMirrorPathExistsError, msg

    dest_parent_contents[dest_basename] = src_key
    self._invoke_delegates('copy_path', src_path, dest_path, src_revnum)

    # Yes sir, src_key and src_contents are also the contents of the
    # destination.  This is a cheap copy, remember!  :-)
    return src_key, src_contents

  def _fill_symbolic_name(self, svn_commit):
    """Performs all copies necessary to create as much of the the tag
    or branch SVN_COMMIT.symbolic_name as possible given the current
    revision of the repository mirror.

    The symbolic name is guaranteed to exist in the Subversion
    repository by the end of this call, even if there are no paths
    under it."""

    symbol_fill = self.symbolings_reader.filling_guide_for_symbol(
        svn_commit.symbolic_name, self.youngest)
    # Get the list of sources for the symbolic name.
    sources = symbol_fill.get_sources()

    if sources:
      symbol = self.symbol_db.get_symbol(svn_commit.symbolic_name)
      if isinstance(symbol, TagSymbol):
        dest_prefix = Ctx().project.get_tag_path(svn_commit.symbolic_name)
      else:
        dest_prefix = Ctx().project.get_branch_path(svn_commit.symbolic_name)

      dest_key = self._open_writable_node(dest_prefix, False)[0]
      self._fill(symbol_fill, dest_prefix, dest_key, sources)
    else:
      # We can only get here for a branch whose first commit is an add
      # (as opposed to a copy).
      dest_path = Ctx().project.get_branch_path(symbol_fill.name)
      if not self._path_exists(dest_path):
        # If our symbol_fill was empty, that means that our first
        # commit on the branch was to a file added on the branch, and
        # that this is our first fill of that branch.
        #
        # This case is covered by test 16.
        #
        # ...we create the branch by copying trunk from the our
        # current revision number minus 1
        source_path = Ctx().project.trunk_path
        entries = self._copy_path(source_path, dest_path,
                                  svn_commit.revnum - 1)[1]
        # Now since we've just copied trunk to a branch that's
        # *supposed* to be empty, we delete any entries in the
        # copied directory.
        for entry in entries:
          del_path = dest_path + '/' + entry
          # Delete but don't prune.
          self._delete_path(del_path)
      else:
        msg = "Error filling branch '" \
              + clean_symbolic_name(symbol_fill.name) + "'.\n"
        msg += "Received an empty SymbolicNameFillingGuide and\n"
        msg += "attempted to create a branch that already exists."
        raise self.SVNRepositoryMirrorInvalidFillOperationError, msg

  def _fill(self, symbol_fill, dest_prefix, dest_key, sources,
            path = None, parent_source_prefix = None,
            preferred_revnum = None, prune_ok = None):
    """Fill the tag or branch at DEST_PREFIX + PATH with items from
    SOURCES, and recurse into the child items.

    DEST_PREFIX is the prefix of the destination directory, e.g.
    '/tags/my_tag' or '/branches/my_branch', and SOURCES is a list of
    FillSource classes that are candidates to be copied to the
    destination.  DEST_KEY is the key in self.nodes_db to the
    destination, or None if the destination does not yet exist.

    PATH is the path relative to DEST_PREFIX.  If PATH is None, we
    are at the top level, e.g. '/tags/my_tag'.

    PARENT_SOURCE_PREFIX is the source prefix that was used to copy
    the parent directory, and PREFERRED_REVNUM is an int which is the
    source revision number that the caller (who may have copied KEY's
    parent) used to perform its copy.  If PREFERRED_REVNUM is None,
    then no revision is preferable to any other (which probably means
    that no copies have happened yet).

    PRUNE_OK means that a copy has been made in this recursion, and
    it's safe to prune directories that are not in
    SYMBOL_FILL._node_tree, provided that said directory has a source
    prefix of one of the PARENT_SOURCE_PREFIX.

    PATH, PARENT_SOURCE_PREFIX, PRUNE_OK, and PREFERRED_REVNUM
    should only be passed in by recursive calls."""

    # Calculate scores and revnums for all sources
    for source in sources:
      src_revnum, score = symbol_fill.get_best_revnum(source.node,
                                                      preferred_revnum)
      source.set_score(score, src_revnum)

    # Sort the sources in descending score order so that we will make
    # a eventual copy from the source with the highest score.
    sources.sort()
    copy_source = sources[0]

    # If there are multiple sources with the same score, and one
    # of them comes from the same prefix as the parent copy, be
    # sure to use that one.
    if parent_source_prefix is not None and copy_source.prefix != parent_source_prefix:
      for source in sources[1:]:
        if copy_source.score > source.score:
          break
        if source.prefix == parent_source_prefix:
          copy_source = source
          break

    src_path = path_join(copy_source.prefix, path)
    dest_path = path_join(dest_prefix, path)

    # Figure out if we shall copy to this destination and delete any
    # destination path that is in the way.
    do_copy = 0
    if dest_key is None:
      do_copy = 1
    elif prune_ok and (parent_source_prefix != copy_source.prefix or
                       copy_source.revnum != preferred_revnum):
      # We are about to replace the destination, so we need to remove
      # it before we perform the copy.
      self._delete_path(dest_path)
      do_copy = 1

    if do_copy:
      dest_key, dest_entries = self._copy_path(src_path, dest_path,
                                               copy_source.revnum)
      prune_ok = 1
    else:
      dest_entries = self._get_node(dest_key)

    # Create the SRC_ENTRIES hash from SOURCES.  The keys are path
    # elements and the values are lists of FillSource classes where
    # this path element exists.
    src_entries = {}
    for source in sources:
      if isinstance(source.node, SVNRevisionRange):
        continue
      for entry, node in source.node.items():
        src_entries.setdefault(entry, []).append(
            FillSource(source.prefix, node))

    if prune_ok:
      # Delete the entries in DEST_ENTRIES that are not in src_entries.
      delete_list = [ ]
      for entry in dest_entries:
        if not src_entries.has_key(entry):
          delete_list.append(entry)
      if delete_list:
        if not self.new_nodes.has_key(dest_key):
          dest_key, dest_entries = self._open_writable_node(dest_path, True)
        # Sort the delete list to get "diffable" dumpfiles.
        delete_list.sort()
        for entry in delete_list:
          self._fast_delete_path(dest_path, dest_entries, entry)

    # Recurse into the SRC_ENTRIES keys sorted in alphabetical order.
    src_keys = src_entries.keys()
    src_keys.sort()
    for src_key in src_keys:
      next_dest_key = dest_entries.get(src_key, None)
      self._fill(symbol_fill, dest_prefix, next_dest_key,
                 src_entries[src_key], path_join(path, src_key),
                 copy_source.prefix, copy_source.revnum, prune_ok)

  def _synchronize_default_branch(self, svn_commit):
    """Propagate any changes that happened on a non-trunk default
    branch to the trunk of the repository.  See
    CVSCommit._post_commit() for details on why this is necessary."""

    for cvs_rev in svn_commit.cvs_revs:
      svn_trunk_path = Ctx().project.make_trunk_path(cvs_rev.cvs_path)
      if cvs_rev.op == OP_ADD or cvs_rev.op == OP_CHANGE:
        if self._path_exists(svn_trunk_path):
          # Delete the path on trunk...
          self._delete_path(svn_trunk_path)
        # ...and copy over from branch
        self._copy_path(cvs_rev.svn_path, svn_trunk_path,
                        svn_commit.motivating_revnum)
      elif cvs_rev.op == OP_DELETE:
        # delete trunk path
        self._delete_path(svn_trunk_path)
      else:
        msg = ("Unknown CVSRevision operation '%s' in default branch sync."
               % cvs_rev.op)
        raise self.SVNRepositoryMirrorUnexpectedOperationError, msg

  def commit(self, svn_commit):
    """Add an SVNCommit to the SVNRepository, incrementing the
    Repository revision number, and changing the repository.  Invoke
    the delegates' _start_commit() method."""

    if svn_commit.revnum == 2:
      self._initialize_repository(svn_commit.get_date())

    self._start_commit(svn_commit)

    if svn_commit.symbolic_name:
      Log().verbose("Filling symbolic name:",
                    clean_symbolic_name(svn_commit.symbolic_name))
      self._fill_symbolic_name(svn_commit)
    elif svn_commit.motivating_revnum:
      Log().verbose("Synchronizing default_branch motivated by %d"
                    % svn_commit.motivating_revnum)
      self._synchronize_default_branch(svn_commit)
    else: # This actually commits CVSRevisions
      if len(svn_commit.cvs_revs) > 1: plural = "s"
      else: plural = ""
      Log().verbose("Committing %d CVSRevision%s"
                    % (len(svn_commit.cvs_revs), plural))
      for cvs_rev in svn_commit.cvs_revs:
        # See comment in CVSCommit._post_commit() for what this is all
        # about.  Note that although asking self._path_exists() is
        # somewhat expensive, we only do it if the first two (cheap)
        # tests succeed first.
        if (cvs_rev.rev == "1.1.1.1"
            and not cvs_rev.deltatext_exists
            and self._path_exists(cvs_rev.svn_path)):
          # This change can be omitted.
          pass
        else:
          if cvs_rev.op == OP_ADD:
            self._add_path(cvs_rev)
          elif cvs_rev.op == OP_CHANGE:
            # Fix for Issue #74:
            #
            # Here's the scenario.  You have file FOO that is imported
            # on a non-trunk vendor branch.  So in r1.1 and r1.1.1.1,
            # the file exists.
            #
            # Moving forward in time, FOO is deleted on the default
            # branch (r1.1.1.2).  cvs2svn determines that this delete
            # also needs to happen on trunk, so FOO is deleted on
            # trunk.
            #
            # Along come r1.2, whose op is OP_CHANGE (because r1.1 is
            # not 'dead', we assume it's a change).  However, since
            # our trunk file has been deleted, svnadmin blows up--you
            # can't change a file that doesn't exist!
            #
            # Soooo... we just check the path, and if it doesn't
            # exist, we do an add... if the path does exist, it's
            # business as usual.
            if not self._path_exists(cvs_rev.svn_path):
              self._add_path(cvs_rev)
            else:
              self._change_path(cvs_rev)

        if cvs_rev.op == OP_DELETE:
          self._delete_path(cvs_rev.svn_path, Ctx().prune)

  def add_delegate(self, delegate):
    """Adds DELEGATE to self.delegates.

    For every delegate you add, as soon as SVNRepositoryMirror
    performs a repository action method, SVNRepositoryMirror will call
    the delegate's corresponding repository action method.  Multiple
    delegates will be called in the order that they are added.  See
    SVNRepositoryMirrorDelegate for more information."""

    self.delegates.append(delegate)

  def _invoke_delegates(self, method, *args):
    """Iterate through each of our delegates, in the order that they
    were added, and call the delegate's method named METHOD with the
    arguments in ARGS."""

    for delegate in self.delegates:
      getattr(delegate, method)(*args)

  def finish(self):
    """Calls the delegate finish method."""

    self._end_commit()
    self._invoke_delegates('finish')
    self.revs_db = None
    self.nodes_db = None


class SVNRepositoryMirrorDelegate:
  """Abstract superclass for any delegate to SVNRepositoryMirror.
  Subclasses must implement all of the methods below.

  For each method, a subclass implements, in its own way, the
  Subversion operation implied by the method's name.  For example, for
  the add_path method, the DumpfileDelegate would write out a
  "Node-add:" command to a Subversion dumpfile, the StdoutDelegate
  would merely print that the path is being added to the repository,
  and the RepositoryDelegate would actually cause the path to be added
  to the Subversion repository that it is creating.
  """

  def start_commit(self, svn_commit):
    """Perform any actions needed to start SVNCommit SVN_COMMIT;
    see subclass implementation for details."""

    raise NotImplementedError

  def mkdir(self, path):
    """PATH is a string; see subclass implementation for details."""

    raise NotImplementedError

  def add_path(self, s_item):
    """S_ITEM is an SVNCommitItem; see subclass implementation for
    details."""

    raise NotImplementedError

  def change_path(self, s_item):
    """S_ITEM is an SVNCommitItem; see subclass implementation for
    details."""

    raise NotImplementedError

  def delete_path(self, path):
    """PATH is a string; see subclass implementation for
    details."""

    raise NotImplementedError

  def copy_path(self, src_path, dest_path, src_revnum):
    """SRC_PATH and DEST_PATH are both strings, and SRC_REVNUM is a
    subversion revision number (int); see subclass implementation for
    details."""

    raise NotImplementedError

  def finish(self):
    """Perform any cleanup necessary after all revisions have been
    committed."""

    raise NotImplementedError

