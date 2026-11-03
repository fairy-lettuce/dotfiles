import textwrap

from pkgnote import kdl, machines
from pkgnote.migrate_v2 import main as migrate_main
from pkgnote.model import PackagesDoc
from pkgnote.resolve import desired_set

OLD = """
tool {
    package "vim" from="pacman" first_installed_on="ruan" {
        installed_on "ruan"
    }
    package "gone" from="pacman" first_installed_on="ruan" {
        installed_on "ruan"
    }
}
uncategorized {
    package "new" from="pacman" first_installed_on="ruan" {
        installed_on "ruan"
        installed_on "tribios"
    }
    package "removed" from="foreign" first_installed_on="ruan"
}
"""

MACHINE = """
machine "ruan" {
    tool include=#true {
        package "gone" include=#false
    }
}
"""


def test_migrate(env):
    env.write_kdl(OLD)
    (env.pacman / "machine_ruan.kdl").write_text(textwrap.dedent(MACHINE))
    assert migrate_main([]) == 0
    text = env.read_kdl()
    assert "installed_on" not in text and "first_installed_on" not in text
    doc = PackagesDoc.load()
    p = {x.name: x.node.props for x in doc.packages()}
    assert p["vim"] == {"from": "pacman", "first-installed-on": "ruan"}
    assert p["gone"]["skip-if"] == "ruan"
    assert p["new"]["install-if"] == "ruan | tribios"
    assert p["removed"]["skip-if"] == "ruan"
    ruan = desired_set(doc, machines.names_for("ruan", machines.load()))
    assert set().union(*ruan.values()) == {"vim", "new"}
    # machine ファイルの無い tribios: 旧モデルどおり uncategorized は installed_on のものだけ
    # (どこにも入っていない "removed" は tribios にも入らない)
    tribios = desired_set(doc, machines.names_for("tribios", machines.load()))
    unc = {x.name for x in doc.packages() if x.is_uncategorized}
    assert set().union(*tribios.values()) & unc == {"new"}
    assert p["removed"]["install-if"] == "ruan"
    # machine_ruan.kdl は残す
    assert (env.pacman / "machine_ruan.kdl").exists()
    assert kdl.loads(text)
