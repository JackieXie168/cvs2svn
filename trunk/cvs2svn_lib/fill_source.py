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

"""This module contains classes describing the sources of symbol fills."""


from __future__ import generators

from cvs2svn_lib.boolean import *
from cvs2svn_lib.set_support import *
from cvs2svn_lib.context import Ctx
from cvs2svn_lib.common import FatalError
from cvs2svn_lib.common import SVN_INVALID_REVNUM
from cvs2svn_lib.svn_revision_range import SVNRevisionRange
from cvs2svn_lib.svn_revision_range import RevisionScores


class FillSource:
  """Representation of a fill source.

  A FillSource keeps track of the paths that have to be filled using a
  specific LOD as source.

  This class holds a SVNRevisionRange instance for each CVSFile that
  has to be filled within the subtree of the repository rooted at
  self._cvs_path.  The SVNRevisionRange objects are stored in a tree
  in which the directory nodes are dictionaries mapping CVSPaths to
  subnodes and the leaf nodes are the SVNRevisionRange objects telling
  for what range of revisions the leaf could serve as a source.

  FillSource objects are able to compute the score for arbitrary
  source revision numbers.  FillSources can be compared; the
  comparison is such that it sorts FillSources in descending order by
  score (higher score implies smaller).

  These objects are used by the symbol filler in SVNRepositoryMirror."""

  def __init__(self, cvs_path, symbol, lod, node_tree, preferred_range=None):
    """Create a scored fill source.

    Members:

      _CVS_PATH -- (CVSPath): the CVSPath described by this FillSource.
      _SYMBOL -- (Symbol) the symbol to be filled.
      _PREFERRED_RANGE -- the SVNRevisionRange that we should prefer
          to use, or None if there is no preference.
      LOD -- (LineOfDevelopment) is the LOD of the source.
      _NODE_TREE -- (dict) a tree stored as a map { CVSPath : node }, where
          subnodes have the same form.  Leaves are SVNRevisionRange instances
          telling the range of SVN revision numbers from which the CVSPath
          can be copied.
      REVNUM -- (int) the SVN revision number with the best score.
      SCORE -- (int) the score of the best revision number and thus of this
          source.

    """

    self._cvs_path = cvs_path
    self._symbol = symbol
    self.lod = lod
    self._node_tree = node_tree
    self._preferred_range = preferred_range

  def _set_node(self, cvs_file, svn_revision_range):
    parent_node = self._get_node(cvs_file.parent_directory, create=True)
    parent_node[cvs_file] = svn_revision_range

  def _get_node(self, cvs_path, create=False):
    if cvs_path == self._cvs_path:
      return self._node_tree
    else:
      parent_node = self._get_node(cvs_path.parent_directory, create=create)
      try:
        return parent_node[cvs_path]
      except KeyError:
        if create:
          node = {}
          parent_node[cvs_path] = node
          return node
        else:
          raise

  def compute_best_revnum(self):
    """Determine the best subversion revision number to use when
    copying the source tree beginning at this source.

    Return (revnum, score) for the best revision found.  If
    SELF._preferred_range is not None and its revision number is
    among the revision numbers with the best scores, return it;
    otherwise, return the oldest such revision."""

    # Aggregate openings and closings from our rev tree
    svn_revision_ranges = self._get_revision_ranges(self._node_tree)

    # Score the lists
    revision_scores = RevisionScores(svn_revision_ranges)

    source_lod, best_revnum, best_score = revision_scores.get_best_revnum()
    assert source_lod == self.lod

    if (
        self._preferred_range is not None
        and revision_scores.get_score(self._preferred_range,) == best_score
        ):
      best_source_lod = self._preferred_range.source_lod
      best_revnum = self._preferred_range.opening_revnum

    if best_revnum == SVN_INVALID_REVNUM:
      raise FatalError(
          "failed to find a revision to copy from when copying %s"
          % self._symbol.name)
    self.revnum, self.score = best_revnum, best_score

  def _get_revision_ranges(self, node):
    """Return a list of all the SVNRevisionRanges at and under NODE.

    Include duplicates.  This is a helper method used by
    compute_best_revnum()."""

    if isinstance(node, SVNRevisionRange):
      # It is a leaf node.
      return [ node ]
    else:
      # It is an intermediate node.
      revision_ranges = []
      for key, subnode in node.items():
        revision_ranges.extend(self._get_revision_ranges(subnode))
      return revision_ranges

  def get_subsources(self, preferred_range):
    """Generate (entry, FillSource) for all direct subsources."""

    if not isinstance(self._node_tree, SVNRevisionRange):
      for cvs_path, node in self._node_tree.items():
        yield (
            cvs_path,
            FillSource(
                cvs_path, self._symbol, self.lod, node, preferred_range
                ),
            )

  def __cmp__(self, other):
    """Comparison operator that sorts FillSources in descending score order.

    If the scores are the same, prefer the source that is taken from
    its preferred_range (if any); otherwise, prefer the one that is
    on trunk.  If all those are equal then use alphabetical order by
    path (to stabilize testsuite results)."""

    return cmp(other.score, self.score) \
           or cmp(other._preferred_range is not None
                  and other.revnum == other._preferred_range.opening_revnum,
                  self._preferred_range is not None
                  and self.revnum == self._preferred_range.opening_revnum) \
           or cmp(self.lod, other.lod)

  def print_tree(self):
    """Print all nodes to sys.stdout.

    This method is included for debugging purposes."""

    print 'TREE LOD = %s' % (self.lod,)
    self._print_subtree(self._node_tree, self._cvs_path, indent_depth=0)
    print 'TREE', '-' * 75

  def _print_subtree(self, node, cvs_path, indent_depth=0):
    """Print all nodes that are rooted at NODE to sys.stdout.

    INDENT_DEPTH is used to indent the output of recursive calls.
    This method is included for debugging purposes."""

    if isinstance(node, SVNRevisionRange):
      print "TREE:", " " * (indent_depth * 2), cvs_path, node
    else:
      print "TREE:", " " * (indent_depth * 2), cvs_path
      for sub_path, sub_node in node.items():
        self._print_subtree(sub_node, sub_path, indent_depth + 1)


class FillSourceSet:
  """A set of FillSources for a given Symbol and CVSPath.

  self._sources holds a FillSource object for each LineOfDevelopment
  that holds some sources needed to fill the subpath rooted at
  self.cvs_path for symbol self._symbol.  The source with the highest
  score should be used to fill self.cvs_path.  Then the caller should
  descend into sub-nodes to see if their 'best revnum' differs from
  their parent's and if it does, take appropriate actions to 'patch
  up' the subtrees."""

  def __init__(self, symbol, cvs_path, sources):
    # The symbol being filled:
    self._symbol = symbol

    # The CVSPath that is being described:
    self.cvs_path = cvs_path

    # A list of sources, sorted in descending order of score.
    self._sources = sources
    for source in self._sources:
      source.compute_best_revnum()
    self._sources.sort()

  def __len__(self):
    return len(self._sources)

  def get_best_source(self):
    return self._sources[0]

  def get_subsource_sets(self, preferred_range):
    """Return a FillSourceSet for each subentry that still needs filling.

    The return value is a map {CVSPath : FillSourceSet} for subentries
    that need filling, where CVSPath is a path under the path handled
    by SELF."""

    source_entries = {}

    for source in self._sources:
      for cvs_path, subsource in source.get_subsources(preferred_range):
        source_entries.setdefault(cvs_path, []).append(subsource)

    retval = {}
    for (cvs_path, source_list) in source_entries.items():
      retval[cvs_path] = FillSourceSet(self._symbol, cvs_path, source_list)

    return retval

  def print_fill_sources(self):
    print "TREE", "=" * 75
    fill_sources = list(self._sources)
    fill_sources.sort(lambda a, b: cmp(a.lod, b.lod))
    for fill_source in fill_sources:
      fill_source.print_tree()


def get_source_set(symbol, range_map):
  """Return a FillSourceSet describing the fill sources for RANGE_MAP.

  SYMBOL is either a Branch or a Tag.  RANGE_MAP is a map { CVSSymbol
  : SVNRevisionRange } as returned by
  SymbolingsReader.get_range_map().

  Use the SVNRevisionRanges from RANGE_MAP to create a FillSourceSet
  instance describing the sources for filling SYMBOL."""

  # A map { LOD : FillSource } for each LOD containing sources that
  # need to be filled.
  fill_sources = {}

  root_cvs_directory = Ctx()._cvs_file_db.get_file(
      symbol.project.root_cvs_directory_id
      )
  for cvs_symbol, svn_revision_range in range_map.items():
    source_lod = svn_revision_range.source_lod
    try:
      fill_source = fill_sources[source_lod]
    except KeyError:
      fill_source = FillSource(root_cvs_directory, symbol, source_lod, {})
      fill_sources[source_lod] = fill_source

    fill_source._set_node(cvs_symbol.cvs_file, svn_revision_range)

  return FillSourceSet(symbol, root_cvs_directory, fill_sources.values())

