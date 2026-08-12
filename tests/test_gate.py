from houdini_codemode.transport.gate import mutex_name


def test_mutex_name_matches_legacy_cli_namespace() -> None:
    assert mutex_name("LOCALHOST", 18811) == "Local\\houdini-cli-31c91e702010d59d"
