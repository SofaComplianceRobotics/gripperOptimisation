"""Consistency checks for the cross-component name contract in names.py."""

from generation._gripper_common import params_from_config
from geometry.params import ModelParams
from names import (
    CENTERPARTS_DIRNAME,
    GRIPPER_COLLISION_STL,
    GRIPPER_NAME,
    GRIPPER_PRINT_NAME,
    LEG_NAME,
)


def test_default_export_stem_is_the_gripper_name():
    # SOFA loads the center part by GRIPPER_NAME; the export must produce it.
    assert ModelParams().export_stem == GRIPPER_NAME


def test_collision_stl_derives_from_gripper_name():
    assert GRIPPER_COLLISION_STL == f"{GRIPPER_NAME}_collision.stl"


def test_fine_export_stem_never_overwrites_sim_mesh():
    fine = params_from_config({}, ModelParams(), fine=True)
    assert fine.export_stem == GRIPPER_PRINT_NAME
    assert fine.export_stem != GRIPPER_NAME


def test_names_are_nonempty_strings():
    for name in (GRIPPER_NAME, GRIPPER_PRINT_NAME, LEG_NAME, CENTERPARTS_DIRNAME):
        assert isinstance(name, str) and name