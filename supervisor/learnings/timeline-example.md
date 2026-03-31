# RDMA Agent Supervision Timeline

Started: 2026-03-23T18:59:17+00:00

## Cycle 1 — 2026-03-23T18:59:17
**Metrics:** ok=10 timeouts=0 cq_err=22 recv=0 max_token=0
**Patterns:** NORMAL
**Key Events:**
```
  ⎿  [FABRIC GPU0 NIC0] STAGING MR OK: staging=0x7fa7a8000000 key=0x500013 size=953MB
  The safety check at line 1490 already catches this: if (src_off > ctx->buffer_size || dst_off > ctx->buffer_size) → skip. So these out-of-range PUTs are skipped. But the CQ error might come from the FIRST write
  Actually — the CQ error 7 might be an asynchronous error from a DIFFERENT write. Let me check if ANY write has a valid in-range offset. With gpu_off = 0x224 = 548 for the first data PUT (small metadata), that's
  well within range. The CQ error might be from the SECOND or THIRD D2H PUT that has a larger offset.
  The fix: the staging buffer needs to be at LEAST as large as the maximum possible offset. Or: the safety check should also apply to the staging offset, not just log and skip but also avoid the CQ error.
  Actually, the safety check at line 1490 already skips PUTs with out-of-range offsets. But the first PUT (548 bytes at offset 0x224) succeeds and goes through fi_writemsg. The CQ error might be from the remote
  - CQ error prov_errno=7 from writes where offsets exceed buffer_size (meta/NVL regions)
  - CPU dispatch timeout waiting for moe_recv_expert_counter — data doesn't reach GPU because the CQ error prevents the staging→GPU copy
  The next step: the CQ error stops the staging→GPU copy for ALL data (not just the out-of-range writes). Need to handle CQ errors gracefully and still process valid completions. Or: expand the staging to cover the
  A zero MR key on the remote side means fi_writemsg writes with rkey=0 → the remote rejects with prov_errno=7.
● Bash(kubectl logs -n gpu-transport workload-pod-0 2>&1 | strings | grep "CQ error" | wc -l
      echo "total CQ errors on Pod-0"…)
     total CQ errors on Pod-0
     total CQ errors on Pod-1
● 7 + 6 = 13 CQ errors across both pods. With 8 GPUs per pod sending 3 D2H PUTs each, that's 24 writes per direction. Most are failing.
```


## Cycle 2 — 2026-03-23T19:04:17
**Metrics:** ok=10 timeouts=0 cq_err=22 recv=0 max_token=0
**Patterns:** NORMAL
**Key Events:**
```
  ⎿  [FABRIC GPU0 NIC0] STAGING MR OK: staging=0x7fa7a8000000 key=0x500013 size=953MB
  The safety check at line 1490 already catches this: if (src_off > ctx->buffer_size || dst_off > ctx->buffer_size) → skip. So these out-of-range PUTs are skipped. But the CQ error might come from the FIRST write
  Actually — the CQ error 7 might be an asynchronous error from a DIFFERENT write. Let me check if ANY write has a valid in-range offset. With gpu_off = 0x224 = 548 for the first data PUT (small metadata), that's
  well within range. The CQ error might be from the SECOND or THIRD D2H PUT that has a larger offset.
  The fix: the staging buffer needs to be at LEAST as large as the maximum possible offset. Or: the safety check should also apply to the staging offset, not just log and skip but also avoid the CQ error.
  Actually, the safety check at line 1490 already skips PUTs with out-of-range offsets. But the first PUT (548 bytes at offset 0x224) succeeds and goes through fi_writemsg. The CQ error might be from the remote
  - CQ error prov_errno=7 from writes where offsets exceed buffer_size (meta/NVL regions)
  - CPU dispatch timeout waiting for moe_recv_expert_counter — data doesn't reach GPU because the CQ error prevents the staging→GPU copy
  The next step: the CQ error stops the staging→GPU copy for ALL data (not just the out-of-range writes). Need to handle CQ errors gracefully and still process valid completions. Or: expand the staging to cover the
  A zero MR key on the remote side means fi_writemsg writes with rkey=0 → the remote rejects with prov_errno=7.
● Bash(kubectl logs -n gpu-transport workload-pod-0 2>&1 | strings | grep "CQ error" | wc -l
      echo "total CQ errors on Pod-0"…)
     total CQ errors on Pod-0
     total CQ errors on Pod-1
● 7 + 6 = 13 CQ errors across both pods. With 8 GPUs per pod sending 3 D2H PUTs each, that's 24 writes per direction. Most are failing.
```


## Cycle 3 — 2026-03-23T19:09:17
**Metrics:** ok=5 timeouts=0 cq_err=27 recv=0 max_token=0
**Patterns:** NORMAL
**Key Events:**
```
  ⎿  [FABRIC GPU0 NIC0] STAGING MR OK: staging=0x7fda3c000000 key=0x70002e size=953MB
     [FABRIC GPU1 NIC0] STAGING MR OK: staging=0x7f4844000000 key=0xa0001c size=953MB
     [FABRIC GPU2 NIC0] STAGING MR OK: staging=0x7fce88000000 key=0xe0000c size=953MB
● All keys are non-zero. Good. The CQ error 7 might be from the 2nd or 3rd D2H PUT where the offset exceeds the buffer. Let me check how many CQ errors vs how many puts:
● Bash(kubectl logs -n gpu-transport workload-pod-0 2>&1 | strings | grep -c "CQ error"
      echo "CQ errors"…)
     CQ errors
● 8 staging copies (one per GPU), 0 skips, 7 CQ errors. The copies succeed but the writes still produce CQ errors. The error might be from the REMOTE side rejecting the write because the remote's staging address
  The prov_errno=7 on EFA means "Local protection error" or "Remote access error". Let me check if it's actually a LOCAL MR issue — the source buffer might not be correctly within the sender's MR:
  Everything checks out mathematically. The CQ error might be from a LATER write (not the first one). Let me check if the first write actually succeeds and only later writes fail:
  The issue might be that CQ errors prevent the receiver from seeing valid completions. The fi_cq_read returns errors which are consumed by fi_cq_readerr, and valid completions are lost.
  Let me commit this diagnostic state and update memory. The CQ error 7 is the remaining blocker — all the addressing is correct but the EFA provider rejects the writes:
      v81j: Staging copy confirmed working, CQ prov_errno=7 persists…)
  ⎿  [master 2a175ec] v81j: Staging copy confirmed working, CQ prov_errno=7 persists
● Status: Staging copy works (8/8 GPUs), all addresses and keys verify correct, but EFA provider rejects writes with prov_errno=7. This is likely an EFA-specific issue with the FI_MR_PROV_KEY mode — the
```


## Cycle 4 — 2026-03-23T19:14:17
**Metrics:** ok=5 timeouts=0 cq_err=27 recv=0 max_token=0
**Patterns:** NORMAL
**Key Events:**
```
  ⎿  [FABRIC GPU0 NIC0] STAGING MR OK: staging=0x7fda3c000000 key=0x70002e size=953MB
     [FABRIC GPU1 NIC0] STAGING MR OK: staging=0x7f4844000000 key=0xa0001c size=953MB

<!-- ... additional cycles omitted for brevity ... -->
