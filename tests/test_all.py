from cuemsengine import __version__ as version

def test_version():
    version_split = version.split(".")
    assert isinstance(version, str)
    assert len(version) > 0
    assert len(version_split) == 3
    assert version_split[0].isdigit()
    assert version_split[1].isdigit()

    # Allow for a revision number
    revision_split = version_split[2].split("-")
    assert revision_split[0].isdigit()
    if len(revision_split) == 2:
        assert revision_split[1][:3] == "rev"
        assert revision_split[1][3:].isdigit()
