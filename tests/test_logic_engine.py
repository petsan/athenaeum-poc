from athenaeum_brain.logic_engine import check_validity

def test_modus_ponens_valid():
    assert check_validity(["P", "P -> Q"], "Q")["valid"] is True

def test_modus_tollens_valid():
    assert check_validity(["not Q", "P -> Q"], "not P")["valid"] is True

def test_hypothetical_syllogism_valid():
    assert check_validity(["P -> Q", "Q -> R"], "P -> R")["valid"] is True

def test_disjunctive_syllogism_valid():
    assert check_validity(["P or Q", "not P"], "Q")["valid"] is True

def test_affirming_the_consequent_invalid_with_real_counterexample():
    result = check_validity(["Q", "P -> Q"], "P")
    assert result["valid"] is False
    assert result["counterexample"]["P"] is False
    assert result["counterexample"]["Q"] is True

def test_denying_the_antecedent_invalid():
    assert check_validity(["not P", "P -> Q"], "not Q")["valid"] is False
