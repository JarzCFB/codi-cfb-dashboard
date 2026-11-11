# V3 scheduled PLAY/PASS locks

At **8:00 AM America/Chicago every Tuesday**, freeze all regular-season
Tuesday-Friday games. At **8:00 AM America/Chicago every Saturday**, freeze
Saturday games. Sunday/Monday games are outside these two windows.

The workflow fetches current CFBD schedule, current sportsbook quotes and
as-of model inputs. Every scheduled game in the window receives one record,
including **PASS** when there is no live quote, no eligible model projection,
an unsupported matchup, or less than a three-point V3 edge. **PLAY** is
paper-only and requires a valid quoted spread, price within -200..+200 and
V3 edge >= 3. A PLAY is not an injury clearance or wagering instruction.

Each dated CSV is write-once by application rule and paired with a SHA-256
checksum. Git history records subsequent commits. This is an append-only
workflow convention, **not tamper-proof storage**: repository admins can
rewrite Git history. To obtain stronger immutability, protect the branch and
export locks to a retention-controlled external archive.

A workflow run outside exactly 8 AM local is rejected; two UTC cron hours
cover DST. GitHub scheduled jobs can be delayed, and the Python guard will
fail rather than falsely claim an 8 AM lock. Existing prospective first-
qualifying picks remain untouched. The scheduled job may need operational
monitoring for delayed/missed cron runs and API availability.
