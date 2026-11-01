# Synthetic code diff review brief

This is a fictional Python change. Identifiers below are synthetic labels,
not real Git commits. No tests have been run.

## Goal and reviewed version

Review change `synthetic-cache-v1` relative to `synthetic-base-v1`. Identify
defects supported by the supplied code and contract. Do not edit the code.

## Contract and surrounding code

`get_profile(user_id, refresh=False)` returns the requested user's profile.
`fetch_profile(user_id)` is a synchronous read that either returns a dictionary
or raises `ProfileUnavailable`. A refresh failure must leave a previously
cached profile available to later calls. The cache begins as an empty process-
local dictionary. Profiles for different users must remain independent.

Original complete function:

```python
cache = {}


def get_profile(user_id, refresh=False):
    if not refresh and user_id in cache:
        return cache[user_id]
    profile = fetch_profile(user_id)
    cache[user_id] = profile
    return profile
```

Proposed complete diff:

```diff
 def get_profile(user_id, refresh=False):
-    if not refresh and user_id in cache:
-        return cache[user_id]
+    if refresh:
+        cache.clear()
+    if cache:
+        return next(iter(cache.values()))
     profile = fetch_profile(user_id)
     cache[user_id] = profile
     return profile
```

The author claims this makes refresh simpler while preserving behavior.
No caller changes or additional contracts were supplied. Concurrency and cache
expiry are outside this change's stated scope.

## Acceptance criteria

Tie findings to concrete call sequences and the stated contract. Cover multiple
users and a failed refresh. Propose minimal corrections and regression checks;
mark the checks unrun and do not infer test success from inspecting the code.
State limitations of reviewing the supplied text alone.
