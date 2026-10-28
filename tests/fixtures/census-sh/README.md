Fixtures for the census.sh `--help` output tests.

`usage.txt` and `sessions-usage.txt` hold the lines both census `--help`
routes must carry: the usage line for each entry point and the first
exit-code line. The help text itself is the package constant
`noni.shim_help.CENSUS_SH_HELP` / `CENSUS_SESSIONS_SH_HELP`, which the shim
and `noni census --help` both print; the fixtures name the lines that
constant must keep, so the tests compare both routes against them.
