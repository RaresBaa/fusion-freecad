"""Toolbar layout for the Fusion workbench.

The goal is one workspace with Fusion 360's grouping (Create / Modify / Construct /
Inspect) built from existing Sketcher and PartDesign commands, so there is no
switching between workbenches for everyday part modelling.
"""

TOOLBARS = [
    ("Sketch", ["PartDesign_NewSketch"]),
    ("Create", ["PartDesign_Pad", "PartDesign_Pocket", "PartDesign_Revolution",
                "PartDesign_Groove", "PartDesign_Hole", "PartDesign_AdditiveLoft",
                "PartDesign_AdditivePipe", "PartDesign_SubtractiveLoft"]),
    ("Modify", ["FusionFreeCAD_PressPull", "PartDesign_Fillet", "PartDesign_Chamfer",
                "PartDesign_Draft", "PartDesign_Thickness", "PartDesign_Boolean"]),
    ("Pattern", ["PartDesign_Mirrored", "PartDesign_LinearPattern",
                 "PartDesign_PolarPattern", "PartDesign_MultiTransform"]),
    ("Construct", ["PartDesign_Body", "PartDesign_Plane", "PartDesign_Line",
                   "PartDesign_Point", "PartDesign_CoordinateSystem",
                   "PartDesign_ShapeBinder", "PartDesign_SubShapeBinder"]),
    ("Inspect", ["Std_Measure", "Std_MeasureDistance"]),
]


def available(commands):
    """Drop commands this FreeCAD build doesn't have, so toolbars never show blanks."""
    import FreeCADGui as Gui

    known = set(Gui.listCommands())
    return [c for c in commands if c in known]
