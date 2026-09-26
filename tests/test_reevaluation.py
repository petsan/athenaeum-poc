from athenaeum_brain.reevaluation import is_material

def answer_with(grades_at_use):
    return {"source_grades_at_use": grades_at_use}

def test_no_change_not_material():
    a = answer_with({"src1": {"grade": "provisionally_accepted", "version": 0}})
    current = {"src1": {"grade": "provisionally_accepted", "version": 0}}
    result = is_material(a, current)
    assert result["material"] is False
    assert result["reasons"] == []

def test_newly_contested_is_material_regardless_of_threshold():
    a = answer_with({"src1": {"grade": "foundational", "version": 0}})
    current = {"src1": {"grade": "contested", "version": 1}}
    # even with a very high threshold, "newly contested" fires on its own (Rule 1)
    result = is_material(a, current, threshold=10)
    assert result["material"] is True
    assert "newly contested" in result["reasons"][0]

def test_small_improvement_below_threshold_not_material():
    a = answer_with({"src1": {"grade": "provisionally_accepted", "version": 0}})
    current = {"src1": {"grade": "foundational", "version": 1}}  # one band up
    result = is_material(a, current, threshold=2)
    assert result["material"] is False

def test_large_change_above_threshold_is_material():
    a = answer_with({"src1": {"grade": "foundational", "version": 0}})
    current = {"src1": {"grade": "provisionally_accepted", "version": 1}}
    result = is_material(a, current, threshold=1)
    assert result["material"] is True

def test_source_not_yet_graded_live_is_not_treated_as_a_change():
    a = answer_with({"src1": {"grade": "provisionally_accepted", "version": 0}})
    result = is_material(a, current_grades={})  # no live grade available at all
    assert result["material"] is False

def test_multiple_sources_all_reasons_reported():
    a = answer_with({
        "src1": {"grade": "foundational", "version": 0},
        "src2": {"grade": "provisionally_accepted", "version": 0},
    })
    current = {
        "src1": {"grade": "rejected", "version": 2},          # severe -- material
        "src2": {"grade": "provisionally_accepted", "version": 0},  # unchanged
    }
    result = is_material(a, current)
    assert result["material"] is True
    assert len(result["reasons"]) == 1
    assert "src1" in result["reasons"][0]


# --- owner decision 9 (2026-09-26): only downgrades are material -------------

def test_an_upgrade_is_never_material_however_large():
    a = answer_with({"src1": {"grade": "contested", "version": 0}})
    current = {"src1": {"grade": "foundational", "version": 3}}   # two bands up
    assert is_material(a, current, threshold=1) == {"material": False, "reasons": []}


def test_an_upgrade_driven_by_a_standard_amendment_is_not_material_either():
    a = answer_with({"src1": {"grade": "provisionally_accepted", "version": 0, "standard_version": 0}})
    current = {"src1": {"grade": "foundational", "version": 1, "standard_version": 1}}
    prior = {"src1": "provisionally_accepted"}   # the old standard wouldn't give 'foundational'
    assert not is_material(a, current, prior_standard_grades=prior)["material"]


def test_a_one_band_downgrade_is_still_material():
    a = answer_with({"src1": {"grade": "foundational", "version": 0}})
    current = {"src1": {"grade": "provisionally_accepted", "version": 1}}
    result = is_material(a, current, threshold=1)
    assert result["material"] and "foundational -> provisionally_accepted" in result["reasons"][0]
