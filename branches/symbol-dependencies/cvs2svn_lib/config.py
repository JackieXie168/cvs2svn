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

"""This module contains various configuration constants used by cvs2svn."""


from cvs2svn_lib.boolean import *


SVN_KEYWORDS_VALUE = 'Author Date Id Revision'

# The default names for the trunk/branches/tags directory for each
# project:
DEFAULT_TRUNK_BASE = 'trunk'
DEFAULT_BRANCHES_BASE = 'branches'
DEFAULT_TAGS_BASE = 'tags'

SVNADMIN_EXECUTABLE = 'svnadmin'
CO_EXECUTABLE = 'co'
CVS_EXECUTABLE = 'cvs'
SORT_EXECUTABLE = 'sort'

# The first file contains enough information about each CVSRevision to
# deduce preliminary Changesets.  The second file is a sorted version
# of the first.
CVS_REVS_SUMMARY_DATAFILE = 'cvs2svn-revs-summary.txt'
CVS_REVS_SUMMARY_SORTED_DATAFILE = 'cvs2svn-revs-summary-s.txt'

# The first file contains enough information about each CVSSymbol to
# deduce preliminary Changesets.  The second file is a sorted version
# of the first.
CVS_SYMBOLS_SUMMARY_DATAFILE = 'cvs2svn-symbols-summary.txt'
CVS_SYMBOLS_SUMMARY_SORTED_DATAFILE = 'cvs2svn-symbols-summary-s.txt'

# A mapping from CVSItem id to Changeset id.
CVS_ITEM_TO_CHANGESET = 'cvs2svn-cvs-item-to-changeset.dat'

# A mapping from CVSItem id to Changeset id, after the
# RevisionChangeset loops have been broken.
CVS_ITEM_TO_CHANGESET_REVBROKEN = \
    'cvs2svn-cvs-item-to-changeset-revbroken.dat'

# A mapping from CVSItem id to Changeset id, after all Changeset
# loops have been broken.
CVS_ITEM_TO_CHANGESET_ALLBROKEN = \
    'cvs2svn-cvs-item-to-changeset-allbroken.dat'

# A mapping from id to Changeset.
CHANGESETS_DB = 'cvs2svn-changesets.db'

# A mapping from id to Changeset, after the RevisionChangeset loops
# have been broken.
CHANGESETS_REVBROKEN_DB = 'cvs2svn-changesets-revbroken.db'

# A mapping from id to Changeset, after the RevisionChangesets have
# been sorted and converted into OrderedChangesets.
CHANGESETS_REVSORTED_DB = 'cvs2svn-changesets-revsorted.db'

# A mapping from id to Changeset, after all Changeset loops have been
# broken.
CHANGESETS_ALLBROKEN_DB = 'cvs2svn-changesets-allbroken.db'

# The RevisionChangesets in commit order.  Each line contains the
# changeset id and timestamp of one changeset, in hexadecimal, in the
# order that the changesets should be committed to svn.
CHANGESETS_SORTED_DATAFILE = 'cvs2svn-changesets-s.txt'

# This file contains a marshalled copy of all the statistics that we
# gather throughout the various runs of cvs2svn.  The data stored as a
# marshalled dictionary.
STATISTICS_FILE = 'cvs2svn-statistics.pck'

# A file holding the lifetime of every CVSItem that has been seen.
LIFETIME_DB = 'cvs2svn-cvs-item-lifetimes.dat'

# Skeleton version of an svn filesystem.  See class
# SVNRepositoryMirror for how these work.
SVN_MIRROR_REVISIONS_TABLE = 'cvs2svn-svn-revisions.dat'
SVN_MIRROR_NODES_INDEX_TABLE = 'cvs2svn-svn-nodes-index.dat'
SVN_MIRROR_NODES_STORE = 'cvs2svn-svn-nodes.pck'

# Pickled map of CVSFile.id to instance.
CVS_FILES_DB = 'cvs2svn-cvs-files.pck'

# A series of records.  The first is a pickled serializer.  Each
# subsequent record is a serialized list of all CVSItems applying to a
# CVSFile.
CVS_ITEMS_STORE = 'cvs2svn-cvs-items.pck'

# A database of filtered CVSItems.  Excluded symbols have been
# discarded (and the dependencies of the remaining CVSItems fixed up).
# These two files are used within an IndexedCVSItemStore; the first is
# a map id-> offset, and the second contains the pickled CVSItems at
# the specified offsets.
CVS_ITEMS_FILTERED_INDEX_TABLE = 'cvs2svn-cvs-items-filtered-index.pck'
CVS_ITEMS_FILTERED_STORE = 'cvs2svn-cvs-items-filtered.pck'

# A record of all symbolic names that will be processed in the
# conversion.  This file contains a pickled list of TypedSymbol
# objects.
SYMBOL_DB = 'cvs2svn-symbols.pck'

# A pickled list of the statistics for all symbols.  Each entry in the
# list is an instance of cvs2svn_lib.symbol_statistics._Stats.
SYMBOL_STATISTICS_LIST = 'cvs2svn-symbol-stats.pck'

# This database maps Subversion revision numbers to pickled SVNCommit
# instances.
SVN_COMMITS_INDEX_TABLE = 'cvs2svn-svn-commits-index.dat'
SVN_COMMITS_STORE = 'cvs2svn-svn-commits.pck'

# How many bytes to read at a time from a pipe.  128 kiB should be
# large enough to be efficient without wasting too much memory.
PIPE_READ_SIZE = 128 * 1024

# Records the author and log message for each changeset.  The database
# contains a map metadata_id -> (author, logmessage).  Each
# CVSRevision that is eligible to be combined into the same SVN commit
# is assigned the same id.  Note that the (author, logmessage) pairs
# are not necessarily all distinct; other data are taken into account
# when constructing ids.
METADATA_DB = "cvs2svn-metadata.db"

# If this run's output is a repository, then (in the tmpdir) we use
# a dumpfile of this name for repository loads.
#
# If this run's output is a dumpfile, then this is default name of
# that dumpfile, but in the current directory (unless the user has
# specified a dumpfile path, of course, in which case it will be
# wherever the user said).
DUMPFILE = 'cvs2svn-dump'

# flush a commit if a 5 minute gap occurs.
COMMIT_THRESHOLD = 5 * 60

