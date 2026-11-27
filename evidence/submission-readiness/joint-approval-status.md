# Proposed final wording for joint review

Joint approval of changes to the rules and interrupted-pot handling is pending. The following describes current runtime behavior.

## Tested rules

- One room per process with seats A and B and virtual chips. The host
  sets an even integer bet unit from 2 through 20 at creation. Each
  player starts with 20 units. The small blind is half a unit and the
  big blind is one unit.
- A is the first button. The dealer posts small blind and acts first
  preflop. The nondealer posts big blind and acts first postflop.
  Deal two cards each, alternating from the button, from a unique
  52-card deck. Reveal 3/1/1 community cards without burns.
- A bet or raise increment is one unit on every street. The big
  blind counts as the opener. A street allows two raises beyond
  the opener. Check requires nothing owed. Calling pays the amount
  owed. An initial small-blind call preserves the big blind's option.
  Fold remains
  legal for the acting player. Payments require the acting player
  to retain one chip. The current engine has no opponent-coverage
  guard for a bet or raise. All-ins, side pots and custom amounts
  are outside this variant.
- A fold awards the pot once without revealing the opponent's
  cards. At showdown, compare the best five from seven and settle
  once. A tie splits the pot and any odd chip goes to the dealer.
  A settled hand has zero pot and no actor.
- Both players Ready for a new hand, which rotates the button and
  preserves the settled balances before posting new blinds. A match
  stops after settlement if either stack is at or below one full
  bet unit. No next hand is dealt.
- Gameplay activation requires both current gameplay connections.
  The authoritative turn is 30 seconds. At expiry the server
  checks when legal, otherwise folds. After activation, each absence
  starts a 20-second grace period. Timely reconnect preserves the
  saved time. Expiry with one player present forfeits to that seat.
  If both are absent at the first expiry, the match closes without
  a winner. A command at the deadline is late.

## Interrupted pot wording

Disconnect termination records a match result separately from hand
settlement. An interrupted hand retains its existing stacks and
outstanding unawarded pot. Private opponent cards stay hidden. Any
previously settled payout remains valid. Reconnection can observe the
terminal state and cannot reopen it.

## Items to approve

- Accept the above variant or approve a specific migration. The older
  draft differs on 500-chip stacks, fixed blinds, street-dependent
  increments, three raises, burns, opponent affordability, odd chips,
  and the next-blind exhaustion rule.
- Accept the above interrupted-pot wording or jointly define a change
  and its accounting, privacy, and test obligations.

[Engine](../../poker/engine.py) · [Timers](../../server/timers.py) ·
[Protocol](../../docs/protocol.md) · [Target draft](../../docs/rules.md) ·
[Discrepancy ledger](../final-correctness-audit/specification-discrepancies.md)
