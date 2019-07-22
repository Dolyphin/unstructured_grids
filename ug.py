# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####

# <pep8 compliant>

# Core classes and routines for Unstructured Grids

import bpy
import logging
l = logging.getLogger(__name__)

obname = "Unstructured Grid" # Name for the Blender object
ugcells = [] # global list of all UGCells
ugfaces = [] # global list of all UGFaces
ifaces0 = -1 # constant value of internal faces after import
ugverts = [] # global list of all UGVerts
ugboundaries = [] # global list of all UGBoundaries
fulldebug = False # Set to True if you wanna see walls of logging debug

class UGCell:
    '''Class for Unstructured Grid cell data objects'''

    deleted = False # boolean for marking deleted cells
    ugfaces = [] # list ugfaces that make up this cell
    ei = -1 # Cell index (used at export only)
    ii = -1 # Internal index (used for debugging

    def __init__(self):
        '''Initialize UGCell with cell index'''
        self.ugfaces = []
        self.ii = len(ugcells)
        ugcells.append(self)


class UGFace:
    '''Class for Unstructured Grid face data objects'''

    deleted = False # boolean for marking deleted faces
    owner = None # UGCell owning this face
    neighbour = None # UGCell neighbouring this face
    bi = -1 # Blender face index corresponding to this UGFace
    ei = -1 # Face index (used at export only)
    mati = -1 # Blender material slot index number
    ugverts = [] # list of ordered ugverts used by this face

    def __init__(self, verts):
        '''Initialize UGFace with vertex index list'''
        self.ugverts = []
        for v in verts:
            self.ugverts.append(ugverts[v])
        ugfaces.append(self)


class UGVertex:
    '''Class for Unstructured Grid vertex data object'''

    deleted = False # boolean for marking deleted vertex
    bi = -1 # Blender vertex index corresponding to this UGVertex
    ei = -1 # Vertex index (used at export only)

    def __init__(self, i):
        '''Initialize UGFace with vertex index'''
        self.bi = i
        ugverts.append(self)


class UGBoundary:
    '''Class for Unstructured Grid patch (boundary face) objects'''

    deleted = False # boolean for patches which contain zero boundary faces
    patchname = 'default' # patch name
    typename = 'default' # patch type name
    inGroups = '' # name for patch group this patch is part of
    nFaces = 0 # number of faces in patch
    startFace = -1 # index to first face for this patch (used at export only)
    mati = -1 # Blender object material slot index number of this boundary patch
    # TODO: Remove mati? This is redunant since index in ugboundaries matches slot index
    ugfaces = [] # list of UGFaces that are part of this boundary patch (updated after changes)

    def __init__(self, patchname):
        '''Initialize UGBoundary with name patchname'''
        self.ugfaces = []
        self.patchname = patchname
        self.mati = len(ugboundaries)
        ugboundaries.append(self)


def initialize_ug_object():
    '''Creates and returns an initialized and empty UG mesh object and
    initializes UG data
    '''

    # Zero UG data
    ugverts = []
    ugfaces = []
    ugcells = []
    ugboundaries = []

    # Initialize mesh object
    if obname in bpy.data.objects:
        l.debug("Delete existing object " + obname)
        bpy.ops.object.select_all(action='DESELECT')
        bpy.data.objects[obname].select_set(True)
        mesh = bpy.data.objects[obname].data
        bpy.ops.object.delete()
        bpy.data.meshes.remove(mesh)

    l.debug("Create and activate new mesh object " + obname)
    mesh_data = bpy.data.meshes.new(obname)
    ob = bpy.data.objects.new(obname, mesh_data)
    bpy.context.scene.collection.objects.link(ob)
    bpy.context.view_layer.objects.active = bpy.data.objects[obname]
    ob.select_set(True)

    return ob


def get_ug_object():
    '''Returns UG object'''

    if obname in bpy.data.objects:
        return bpy.data.objects[obname]
    l.error("No object named " + obname)
    return None


class UG_OT_UpdateBoundariesFromFaceMaterials(bpy.types.Operator):
    '''Run after any changes to material slot or face material assignments.
    Materials are used to define boundary patch name and face assignments.
    '''
    bl_idname = "unstructured_grids.update_ugboundaries"
    bl_label = "Update UG Boundaries From Materials"

    def execute(self, context):
        update_ugboundaries()
        return {'FINISHED'}


def update_ugboundaries():
    '''Updates Boundary definitions and properties according to Materials
    for all boundary faces.
    '''

    ob = get_ug_object()
    # Initialize ugboundaries
    for b in ugboundaries:
        b.deleted = True
        b.ugfaces = []
        b.nFaces = 0
        b.startFace = -1

    # Process all boundary faces
    for i in range(len(ugfaces)):
        f = ugfaces[i]
        if f.deleted:
            continue
        if f.neighbour:
            continue

        mati = ob.data.polygons[f.bi].material_index
        mat = ob.material_slots[mati]

        while (mati >= len(ugboundaries)):
            UGBoundary("new")

        patch = ugboundaries[mati]
        patch.patchname = mat.name

        patch.deleted = False
        patch.ugfaces.append(f)

    # Update number of faces in boundaries. Note: startFace is updated at export.
    for b in ugboundaries:
        b.nFaces = len(b.ugfaces)
        l.debug("Faces on patch %s: %d" %(b.patchname, b.nFaces))

    return None


def get_next_undeleted_cell(clist, ind):
    '''Finds next undeleted UGCell in clist starting from index ind+1.
    Returns UGCell and it's index in clist.
    '''
    # TODO: Delete function if not needed

    for i in range(ind + 1, len(clist)):
        c = clist[i]
        if not c.deleted:
            return c, i
    return None, None


def order_ugcells():
    '''Return list of ugcells ordered so that each cell is neighbour to
    at least one of the previous cells. Ordered cell list is used
    for exporting UG data to ensure that cell editing result is
    one closed region and to order faces and cells.

    Note: This function uses UGCell.ei to store number of unprocessed
    neighbour cells, to track which cells to include next in the list.
    '''

    def init_ncells():
        '''Initialize ugcells ei property with number of neighbour cells
        and ugfaces ei property with zero.
        '''

        n = 0 # Number of cells
        # Initialize cells
        for c in ugcells:
            if c.deleted:
                c.ei = 0
                continue
            n += 1
            # Initialize with all faces, then decrease number of boundary faces
            c.ei = len(c.ugfaces)
            for f in c.ugfaces:
                if not f.neighbour:
                    c.ei -= 1

        return n

    def get_next_neighbour_cell(c, clist):
        '''Return first neighbour cell next to argument cell c
        which is not in argument cell list.
        '''

        if fulldebug: l.debug("Searching through faces of " + str(c.ii) + " whose c.ei=%d" % c.ei)
        for f in c.ugfaces:
            if fulldebug: l.debug("- checking face " + str(f))
            if not f.neighbour:
                if fulldebug: l.debug("- boundary face")
                continue
            if f.owner == c:
                nc = f.neighbour
            else:
                nc = f.owner
            # Find new path to an unprocessed cell
            if nc in clist:
                if fulldebug: l.debug("- Already in list " + str(nc.ii))
                continue
            if nc.ei > 0:
                # If neighbour is unprocessed, decrease unprocessed cell counts and return
                if fulldebug: l.debug("- Found new cell " + str(nc.ii))
                return nc
            else:
                if fulldebug: l.debug("- nc.ei=%" % nc.ei)

        # No neighbour found
        return None

    def get_next_unfinished_cell(clist):
        '''Return first cell in argument clist which contains neighbours
        not in clist according to ei variable.
        '''

        for c in clist:
            if c.ei > 0:
                return c
        return None

    def decrease_cell_counters(c, clist):
        '''Decreases cell ei index for every cell in clist connected to cell c'''

        for f in c.ugfaces:
            if not f.neighbour:
                continue
            if f.owner == c:
                nc = f.neighbour
            else:
                nc = f.owner
            if nc in clist and nc.ei > 0:
                c.ei -= 1
                nc.ei -= 1
                if fulldebug: l.debug("-- Reduced neighbor count for " + str(nc.ii))


    # Intialize
    print_interval = 1000 # Debug print progress interval
    i = 0
    n = init_ncells()
    clist = [] # list of ordered ugcells, to be populated
    for c in ugcells:
        if c.ei > 0:
            clist.append(c)
            break

    # Process all cells
    for i in range(n-1):
        if fulldebug: l.debug("i=%d, clist len=%d" % (i, len(clist)))
        # Extend clist with a neighbour cell
        c = get_next_unfinished_cell(clist)
        if fulldebug: l.debug("Next unfinished cell is " + str(c.ii) + " after ei=%d" % ((c.ei)-1))
        if not c:
            l.debug("No cell at i=%d" % i)
        nc = get_next_neighbour_cell(c, clist)
        if fulldebug: l.debug("Next neighbour cell is " + str(nc.ii) + " after ei=%d" % nc.ei)
        if not nc:
            l.warning("Region is incomplete! Final cell count %d/%d" % (i, n))
            return clist
        clist.append(nc)
        decrease_cell_counters(nc, clist)
        if i % print_interval == 0:
            l.debug("Ordering cells, progress: %d/%d" % (i, n))

    l.debug("Sorting completed, cell count %d/%d" % (len(clist), n))
    if fulldebug:
        for i in range(len(clist)):
            l.debug(str(i) + " " + str(clist[i]))

    return clist
