"""Consistency checks for the cross-component name contract in names.py."""

from generation._gripper_common import params_from_config
from geometry.leg_params import LegParams
from geometry.params import ModelParams
from names import (
    CENTERPARTS_DIRNAME,
    GRIPPER_COLLISION_FINGER_STLS,
    GRIPPER_COLLISION_STL,
    GRIPPER_NAME,
    GRIPPER_PRINT_NAME,
    LEG_NAME,
    LEG_WORKING_NAME,
)


def test_default_export_stem_is_the_gripper_name():
    # SOFA loads the center part by GRIPPER_NAME; the export must produce it.
    assert ModelParams().export_stem == GRIPPER_NAME


def test_collision_stl_derives_from_gripper_name():
    assert GRIPPER_COLLISION_STL == f"{GRIPPER_NAME}_collision.stl"


def test_finger_collision_stls_derive_from_gripper_name():
    assert GRIPPER_COLLISION_FINGER_STLS == (
        f"{GRIPPER_NAME}_collision_finger1.stl",
        f"{GRIPPER_NAME}_collision_finger2.stl",
    )
    assert len(set(GRIPPER_COLLISION_FINGER_STLS)) == 2


def test_fine_export_stem_never_overwrites_sim_mesh():
    fine = params_from_config({}, ModelParams(), fine=True)
    assert fine.export_stem == GRIPPER_PRINT_NAME
    assert fine.export_stem != GRIPPER_NAME


def test_names_are_nonempty_strings():
    for name in (
        GRIPPER_NAME,
        GRIPPER_PRINT_NAME,
        LEG_NAME,
        LEG_WORKING_NAME,
        CENTERPARTS_DIRNAME,
    ):
        assert isinstance(name, str) and name


def test_default_leg_export_stem_is_the_working_name():
    # The manual "Generate" button and the dashboard's "Launch Test with UI"
    # must never overwrite the shared stock LEG_NAME (blueleg) other labs
    # also read from data/meshes/legs/.
    assert LegParams().export_stem == LEG_WORKING_NAME
    assert LEG_WORKING_NAME != LEG_NAME