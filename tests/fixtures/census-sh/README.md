Fixtures for the census.sh `--help` output tests.

`usage.txt` holds the canonical header the census.sh and census-sessions.sh
`--help` output must contain: the usage line for each entry point and the
first exit-code line. The scripts generate their help from their own header
comment (no hard-coded sed line range), so the help text is stable as long
as the header keeps these lines; the tests assert on these exact strings.
