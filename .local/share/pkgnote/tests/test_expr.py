import pytest

from pkgnote.expr import ExprError, names_in, parse, to_str


def ev(text, *names):
    return parse(text).eval(set(names))


def test_name_and_not():
    assert ev("ruan", "ruan")
    assert not ev("ruan", "tribios")
    assert ev("!ruan", "tribios")
    assert ev("!!ruan", "ruan")


def test_precedence_and_binds_tighter_than_or():
    # a | b & c == a | (b & c)
    assert ev("a | b & c", "a")
    assert not ev("a | b & c", "b")
    assert ev("a | b & c", "b", "c")
    # !a & b == (!a) & b
    assert ev("!a & b", "b")
    assert not ev("!a & b", "a", "b")


def test_parentheses_override():
    assert not ev("(a | b) & c", "a")
    assert ev("(a | b) & c", "a", "c")
    assert ev("!(a & b)", "a")
    assert not ev("!(a & b)", "a", "b")


def test_whitespace_insignificant():
    assert parse(" a&(b|!c) ") == parse("a & ( b | ! c )")


def test_hyphenated_names():
    assert ev("systemd-boot & intel-cpu", "systemd-boot", "intel-cpu")
    assert names_in(parse("nvidia-gpu | !(a & b-c)")) == {"nvidia-gpu", "a", "b-c"}


def test_to_str_roundtrip_minimal_parens():
    for text in ["a | b & c", "(a | b) & c", "!(a | b)", "!a & !b | c", "a & (b | c) & d"]:
        e = parse(text)
        assert parse(to_str(e)) == e
    assert to_str(parse("((a))|(b&c)")) == "a | b & c"


@pytest.mark.parametrize(
    "text, fragment",
    [
        ("ruan tribios", "並置"),
        ("", "空"),
        ("   ", "空"),
        ("a &", "途中で終わって"),
        ("(a | b", "`)` が足りません"),
        ("a | b)", "`(` の無い `)`"),
        ("& a", "左側"),
        ("a | | b", "左側"),
        ("()", "空"),
        ("a , b", "予期しない文字"),
        ("a & $x", "使えない文字"),
    ],
)
def test_syntax_errors(text, fragment):
    with pytest.raises(ExprError) as ei:
        parse(text, where="packages.kdl: tool/package \"x\" の install-if")
    msg = str(ei.value)
    assert fragment in msg
    assert "packages.kdl: tool/package \"x\" の install-if" in msg


def test_error_caret_points_at_position():
    with pytest.raises(ExprError) as ei:
        parse("a & b c")
    assert ei.value.pos == 6
    assert str(ei.value).splitlines()[-1] == "    " + " " * 6 + "^"
