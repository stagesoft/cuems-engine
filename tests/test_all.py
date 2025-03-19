from cuemsengine import __version__ as version

def test_version():
    version_split = version.split(".")
    assert isinstance(version, str)
    assert len(version) > 0
    assert len(version_split) == 3
    for i in version_split:
        assert len(i) >= 0
        assert i.isdigit()
