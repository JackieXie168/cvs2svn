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

# These files are related to the cleaning and sorting of CVS revisions,
# for commit grouping.  See design-notes.txt for details.
CVS_REVS_RESYNC_DATAFILE = 'cvs2svn-revs-resync.txt'
CVS_REVS_SORTED_DATAFILE = 'cvs2svn-revs-resync-s.txt'
RESYNC_DATAFILE = 'cvs2svn-resync.txt'

# This file contains a marshalled copy of all the statistics that we
# gather throughout the various runs of cvs2svn.  The data stored as a
# marshalled dictionary.
STATISTICS_FILE = 'cvs2svn-statistics.pck'

# This text file contains records (1 per line) that describe svn
# filesystem paths that are the opening and closing source revisions
# for copies to tags and branches.  The format is as follows:
#
#     SYMBOL_ID SVN_REVNUM TYPE BRANCH_ID CVS_FILE_ID
#
# Where type is either OPENING or CLOSING.  The SYMBOL_ID and
# SVN_REVNUM are the primary and secondary sorting criteria for
# creating SYMBOL_OPENINGS_CLOSINGS_SORTED.  BRANCH_ID is the symbol
# id of the branch where this opening or closing happened (in hex), or
# '*' for the default branch.  CVS_FILE_ID is the id of the
# corresponding CVSFile (in hex).
SYMBOL_OPENINGS_CLOSINGS = 'cvs2svn-symbolic-names.txt'
# A sorted version of the above file.
SYMBOL_OPENINGS_CLOSINGS_SORTED = 'cvs2svn-symbolic-names-s.txt'

# Skeleton version of an svn filesystem.
# (These supersede and will eventually replace the two above.)
# See class SVNRepositoryMirror for how these work.
SVN_MIRROR_REVISIONS_DB = 'cvs2svn-svn-revisions.db'
SVN_MIRROR_NODES_DB = 'cvs2svn-svn-nodes.db'

# Offsets pointing to the beginning of each symbol's records in
# SYMBOL_OPENINGS_CLOSINGS_SORTED.  This file contains a pickled map
# from symbol_id to file offset.
SYMBOL_OFFSETS_DB = 'cvs2svn-symbol-offsets.pck'

# Maps CVSRevision.ids (in hex) to lists of symbol ids, where the
# CVSRevision is the last such that is a source for those symbols.
# For example, if branch B's number is 1.3.0.2 in this CVS file, and
# this file's 1.3 is the latest (by date) revision among *all* CVS
# files that is a source for branch B, then the CVSRevision.id
# corresponding to this file at 1.3 would list at least the symbol id
# for branch B in its list.
SYMBOL_LAST_CVS_REVS_DB = 'cvs2svn-symbol-last-cvs-revs.db'

# Maps CVSFile.id to instance.
CVS_FILES_DB = 'cvs2svn-cvs-files.db'

# A series of pickles.  The first is a primer.  Each subsequent pickle
# is lists of all CVSItems applying to a CVSFile.
CVS_ITEMS_STORE = 'cvs2svn-cvs-items.pck'

# Maps CVSItem.id (in hex) to CVSRevision after resynchronization.
# The index file contains id->offset, and the second contains the
# pickled CVSItems at the specified offsets.
CVS_ITEMS_RESYNC_INDEX_TABLE = 'cvs2svn-cvs-items-resync-index.dat'
CVS_ITEMS_RESYNC_STORE = 'cvs2svn-cvs-items-resync.pck'

# A record of all symbolic names that will be processed in the
# conversion.  This file contains a pickled list of TypedSymbol
# objects.
SYMBOL_DB = 'cvs2svn-symbols.pck'

# A pickled list of the statistics for all symbols.  Each entry in the
# list is an instance of cvs2svn_lib.symbol_statistics._Stats.
SYMBOL_STATISTICS_LIST = 'cvs2svn-symbol-stats.pck'

# These two databases provide a bidirectional mapping between
# CVSRevision.ids (in hex) and Subversion revision numbers.
#
# The first maps CVSRevision.id to a number; the values are not
# unique.
#
# The second maps Subversion revision numbers (as hex strings) to
# pickled SVNCommit instances.
CVS_REVS_TO_SVN_REVNUMS = 'cvs2svn-cvs-revs-to-svn-revnums.db'
SVN_COMMITS_DB = 'cvs2svn-svn-commits.db'

# How many bytes to read at a time from a pipe.  128 kiB should be
# large enough to be efficient without wasting too much memory.
PIPE_READ_SIZE = 128 * 1024

# Records the project.id, author, and log message for each changeset.
# There are two types of mapping: digest -> metadata_id, and
# metadata_id -> (projet.id, author, logmessage).  The digests are
# computed in such a way that CVS commits that are eligible to be
# combined into the same SVN commit are assigned the same digest.
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
