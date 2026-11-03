"""読み込み時の検査: 綴り間違いや未知の値で条件が黙って無視されないこと。"""

import pytest

from pkgnote.cli import main
from pkgnote.model import PackagesDoc, SchemaError


@pytest.mark.parametrize(
    "text, fragments",
    [
        ('a {\n    package "x" skipif="ruan"\n}\n', ["`skipif`", 'a/package "x"']),
        ('a {\n    package "x" install-If="ruan"\n}\n', ["`install-If`"]),
        ('a installif="ruan" {\n    package "x"\n}\n', ["`installif`", "packages.kdl: a:"]),
        ('a {\n    b {\n        package "x" from="aur"\n    }\n}\n', ['from="aur"', 'a/b/package "x"']),
        ('package "x"\n', ["トップレベル"]),
        ('a {\n    package "x" {\n        note "hi"\n    }\n}\n', ["子ノード"]),
        ('a "oops" {\n    package "x"\n}\n', ["引数"]),
        ('a {\n    package\n}\n', ["パッケージ名"]),
        ('a {\n    package "x" alias=#true\n}\n', ["文字列"]),
    ],
)
def test_invalid_documents_are_rejected(env, text, fragments):
    env.write_kdl(text)
    with pytest.raises(SchemaError) as ei:
        PackagesDoc.load()
    for f in fragments:
        assert f in str(ei.value)


def test_typo_stops_fetch_and_status_without_writing(env, capsys):
    text = 'a {\n    package "x" skipif="ruan"\n}\n'
    env.write_kdl(text)
    env.set_installed(pacman=["x", "y"])
    assert main(["fetch"]) == 1
    assert main(["status"]) == 1
    assert "skipif" in capsys.readouterr().err
    assert env.read_kdl() == text


def test_valid_document_passes(env):
    env.write_kdl(
        'a install-if="ruan" skip-if="work" {\n'
        '    package "x" from="flatpak" alias="X" install-if="ruan" skip-if="laptop"'
        ' first-installed-on="ruan"\n'
        '    package "y"\n'
        "}\n"
    )
    assert len(PackagesDoc.load().packages()) == 2
