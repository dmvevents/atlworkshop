An analysis of the timeline reveals that the process crashes because `fi_writemsg` is targeting garbage addresses (e.g., `fi_addr=2324223838531362932`), meaning the data never arrives at the remote endpoints, leaving remote metadata all zeros. The garbage `fi_addr` values indicate that the `remote_addr` array for libfabric is either uninitialized or incorrectly populated.

Here is a structured plan to help you resolve this issue:

### 1. Fix `remote_addr` Array Initialization
Garbage values typically mean the array was allocated with `malloc` but not zeroed, and some indices were never explicitly populated. 
* **Action:** Find where `ctx->fi_nic[nic_idx].remote_addr` is allocated and change `malloc` to `calloc`, or add a `memset(..., 0, ...)` right after allocation. This ensures unpopulated ranks default to `0` or `FI_ADDR_UNSPEC` rather than random garbage.

### 2. Audit `fi_av_insert` Execution
The libfabric Address Vector (AV) is populated using `fi_av_insert`. 
* **Action:** Check the return value of `fi_av_insert`. It returns the number of addresses successfully inserted. If it returns an error (negative value) or fewer addresses than requested, the `fi_addr` output will remain uninitialized.
* **Action:** Add a log immediately after `fi_av_insert` to print the inserted `fi_addr_t` for each `rank` (e.g., `printf("Inserted rank %d, fi_addr=%llu\n", rank, (unsigned long long)addr);`).

### 3. Check for Self-Communication (`my_rank == dst_rank`)
Some frameworks skip `fi_av_insert` for their *own* rank. 
* **Action:** Check if the destination rank (`cmd.dst_rank`) where the garbage address is seen is actually the process's own rank. EFA does not natively support loopback/self-communication. If `fi_writemsg` is trying to send to its own rank, it will hit the uninitialized entry in `remote_addr` and fail. If self-communication is intended, it must be handled via local memory copies instead of RDMA, or the loopback address must be properly registered.

### 4. Verify OOB EP Name Exchange (TCP)
To insert an address into the AV, endpoints must exchange their exact fabric names.
* **Action:** Ensure that the `addrlen` returned by `fi_getname` matches exactly what is being sent over the TCP socket. EFA endpoint names are larger than typical IP addresses (often 40+ bytes). If the TCP exchange truncates the name, `fi_av_insert` will silently fail or produce an invalid address mapping.
