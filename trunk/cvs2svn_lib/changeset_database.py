# (Be in -*- python -*- mode.)
#
# ====================================================================
# Copyright (c) 2006-2007 CollabNet.  All rights reserved.
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

"""This module contains classes to store changesets."""


from __future__ import generators

from cvs2svn_lib.boolean import *
from cvs2svn_lib.changeset import Changeset
from cvs2svn_lib.changeset import RevisionChangeset
from cvs2svn_lib.changeset import OrderedChangeset
from cvs2svn_lib.changeset import SymbolChangeset
from cvs2svn_lib.changeset import BranchChangeset
from cvs2svn_lib.changeset import TagChangeset
from cvs2svn_lib.record_table import UnsignedIntegerPacker
from cvs2svn_lib.record_table import RecordTable
from cvs2svn_lib.database import IndexedStore
from cvs2svn_lib.serializer import PrimedPickleSerializer


def CVSItemToChangesetTable(filename, mode):
  return RecordTable(filename, mode, UnsignedIntegerPacker())


class ChangesetDatabase(IndexedStore):
  def __init__(self, filename, index_filename, mode):
    primer = (
        Changeset,
        RevisionChangeset,
        OrderedChangeset,
        SymbolChangeset,
        BranchChangeset,
        TagChangeset,
        )
    IndexedStore.__init__(
        self, filename, index_filename, mode, PrimedPickleSerializer(primer))

  def store(self, changeset):
    self.add(changeset)

  def keys(self):
    return list(self.iterkeys())

  def close(self):
    IndexedStore.close(self)

