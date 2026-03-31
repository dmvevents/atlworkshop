Here are the three complete replacement files:

## bolt_internal.h

```cpp
#pragma once

#include "bolt_transport.h"

#include <rdma/fabric.h>
#include <rdma/fi_domain.h>
#include <rdma/fi_endpoint.h>
#include <rdma/fi_rma.h>
#include <rdma/fi_cm.h>

#include <thread>
#include <atomic>
#include <cstring>

#define BOLT_RECV_POOL_COUNT 512
#define BOLT_RECV_BUF_SIZE  256
#define BOLT_NOTIFY_POOL_COUNT 64
#define BOLT_NOTIFY_MAGIC 0xB01TNFYU

struct bolt_notify_msg {
    uint32_t magic;
    uint32_t src_rank;
    uint32_t num_tokens;
    uint32_t total_bytes;
};

struct bolt_write_ctx {
    struct fi_context2 fi_ctx;
    int dest_rank;
    uint32_t num_tokens;
    uint32_t total_bytes;
    bool active;
};

struct bolt_send_ctx {
    struct fi_context2 fi_ctx;
    int buf_idx;
    bool active;
};

struct bolt_recv_ctx {
    struct fi_context2 fi_ctx;
    int buf_idx;
    int nic_idx;
};

struct bolt_context {
    int gpu_id;
    int rank;
    int num_ranks;
    int num_rdma_ranks;

    void *gpu_buffer;
    size_t buffer_size;

    struct fi_info *fi;
    struct fid_fabric *fabric;
    struct fid_domain *domain;

    int num_nics;
    struct {
        struct fid_ep *ep;
        struct fid_cq *cq;        // single combined CQ (TX+RX)
        struct fid_av *av;
        fi_addr_t remote_addr[BOLT_MAX_PEERS];
        void *mr_desc;
    } nic[BOLT_MAX_NICS];

    struct fid_mr *mr;
    uint64_t mr_key;
    bool using_dmabuf;
    void *staging_buffer;
    size_t staging_size;

    // Recv buffer pool (per NIC)
    struct {
        void *pool;
        struct fid_mr *mr;
        void *mr_desc;
        bolt_recv_ctx ctxs[BOLT_RECV_POOL_COUNT];
    } recv[BOLT_MAX_NICS];

    // Notify send buffer pool (per NIC)
    struct {
        void *pool;
        struct fid_mr *mr;
        void *mr_desc;
        bolt_send_ctx ctxs[BOLT_NOTIFY_POOL_COUNT];
        int next_free;
    } notify[BOLT_MAX_NICS];

    // Write contexts (one per peer per NIC)
    bolt_write_ctx write_ctxs[BOLT_MAX_PEERS];

    bolt_dispatch_signal_t *dispatch_signals;
    bolt_recv_signal_t *recv_signals;

    bolt_dispatch_signal_t *host_dispatch_signals;
    bolt_recv_signal_t *host_recv_signals;

    uint64_t remote_vaddr[BOLT_MAX_PEERS];
    uint64_t remote_rkey[BOLT_MAX_PEERS];

    std::thread worker_thread;
    std::atomic<bool> worker_running{false};

    void *cuda_stream;

    size_t msg_prefix_size;
};
```

## transport_fabric.cpp

```cpp
#include "bolt_internal.h"

#include <rdma/fi_cm.h>
#include <rdma/fi_tagged.h>
#include <rdma/fi_rma.h>

#include <cuda.h>
#include <cuda_runtime.h>

#include <cstdio>
#include <cstdlib>
#include <cstring>

static struct fi_info* bolt_get_fi_info(int gpu_id) {
    struct fi_info *hints = fi_allocinfo();
    if (!hints) return nullptr;

    hints->caps = FI_MSG | FI_RMA | FI_WRITE | FI_READ |
                  FI_SEND | FI_RECV |
                  FI_REMOTE_WRITE | FI_REMOTE_READ;
    hints->mode = 0;
    hints->ep_attr->type = FI_EP_RDM;
    hints->domain_attr->threading = FI_THREAD_SAFE;
    hints->domain_attr->mr_mode = FI_MR_VIRT_ADDR | FI_MR_ALLOCATED | FI_MR_PROV_KEY;

    uint32_t fi_version = FI_VERSION(1, 18);
    hints->fabric_attr->prov_name = strdup("efa");

    struct fi_info *info = nullptr;

    hints->caps |= FI_HMEM;
    hints->domain_attr->mr_mode |= FI_MR_HMEM;
    int ret = fi_getinfo(fi_version, nullptr, nullptr, 0, hints, &info);
    if (ret == 0) {
        fprintf(stderr, "[BOLT GPU%d] fi_getinfo OK with FI_HMEM\n", gpu_id);
    } else {
        fprintf(stderr, "[BOLT GPU%d] fi_getinfo+HMEM failed (%d: %s), trying without\n",
                gpu_id, ret, fi_strerror(-ret));
        hints->caps &= ~((uint64_t)FI_HMEM);
        hints->domain_attr->mr_mode &= ~((int)FI_MR_HMEM);
        ret = fi_getinfo(fi_version, nullptr, nullptr, 0, hints, &info);
    }
    if (ret != 0) {
        fprintf(stderr, "[BOLT GPU%d] fi_getinfo failed (%d), trying minimal\n", gpu_id, ret);
        fi_freeinfo(hints);
        hints = fi_allocinfo();
        hints->ep_attr->type = FI_EP_RDM;
        hints->caps = FI_MSG | FI_RMA | FI_WRITE | FI_REMOTE_WRITE | FI_SEND | FI_RECV;
        hints->fabric_attr->prov_name = strdup("efa");
        ret = fi_getinfo(fi_version, nullptr, nullptr, 0, hints, &info);
    }

    fi_freeinfo(hints);

    if (ret != 0) {
        fprintf(stderr, "[BOLT GPU%d] fi_getinfo FAILED: %d (%s)\n",
                gpu_id, ret, fi_strerror(-ret));
        return nullptr;
    }

    fprintf(stderr, "[BOLT GPU%d] Provider: %s, fabric: %s, domain: %s\n",
            gpu_id, info->fabric_attr->prov_name,
            info->fabric_attr->name, info->domain_attr->name);
    fprintf(stderr, "[BOLT GPU%d] max_msg=%lu, tx_size=%zu, mode=0x%lx, caps=0x%lx, mr_mode=0x%x\n",
            gpu_id, (unsigned long)info->ep_attr->max_msg_size,
            info->tx_attr->size,
            (unsigned long)info->mode,
            (unsigned long)info->caps,
            info->domain_attr->mr_mode);

    return info;
}

static int bolt_register_mr(bolt_context_t *ctx) {
    bool hmem_available = (ctx->fi->caps & FI_HMEM) != 0;

    if (hmem_available) {
        fprintf(stderr, "[BOLT GPU%d] Attempting GPU-direct DMA-BUF MR registration...\n",
                ctx->gpu_id);

        struct fi_mr_attr mr_attr = {};
        struct iovec iov;
        iov.iov_base = ctx->gpu_buffer;
        iov.iov_len = ctx->buffer_size;
        mr_attr.mr_iov = &iov;
        mr_attr.iov_count = 1;
        mr_attr.access = FI_REMOTE_WRITE | FI_REMOTE_READ | FI_WRITE | FI_READ |
                         FI_SEND | FI_RECV;
        mr_attr.iface = FI_HMEM_CUDA;
        mr_attr.device.cuda = ctx->gpu_id;

        int ret = fi_mr_regattr(ctx->domain, &mr_attr, 0, &ctx->mr);
        if (ret == 0) {
            ctx->mr_key = fi_mr_key(ctx->mr);
            ctx->using_dmabuf = true;
            for (int n = 0; n < ctx->num_nics; n++)
                ctx->nic[n].mr_desc = fi_mr_desc(ctx->mr);

            fprintf(stderr, "[BOLT GPU%d] GPU-direct MR OK! key=0x%lx size=%zuMB desc=%p\n",
                    ctx->gpu_id, (unsigned long)ctx->mr_key,
                    ctx->buffer_size / (1024*1024), ctx->nic[0].mr_desc);
            return 0;
        }
        fprintf(stderr, "[BOLT GPU%d] DMA-BUF MR failed (%d: %s), fallback to host\n",
                ctx->gpu_id, ret, fi_strerror(-ret));
    }

    fprintf(stderr, "[BOLT GPU%d] Registering host-pinned buffer (%zuMB)\n",
            ctx->gpu_id, ctx->buffer_size / (1024*1024));

    int ret = fi_mr_reg(ctx->domain, ctx->gpu_buffer, ctx->buffer_size,
                        FI_REMOTE_WRITE | FI_REMOTE_READ | FI_WRITE | FI_READ |
                        FI_SEND | FI_RECV,
                        0, 0, 0, &ctx->mr, nullptr);
    if (ret != 0) {
        fprintf(stderr, "[BOLT GPU%d] Host MR registration failed: %d (%s)\n",
                ctx->gpu_id, ret, fi_strerror(-ret));
        return -1;
    }

    ctx->mr_key = fi_mr_key(ctx->mr);
    ctx->using_dmabuf = false;
    for (int n = 0; n < ctx->num_nics; n++)
        ctx->nic[n].mr_desc = fi_mr_desc(ctx->mr);

    fprintf(stderr, "[BOLT GPU%d] Host MR OK, key=0x%lx desc=%p\n",
            ctx->gpu_id, (unsigned long)ctx->mr_key, ctx->nic[0].mr_desc);
    return 0;
}

static int bolt_setup_recv_pool(bolt_context_t *ctx, int nic_idx) {
    size_t pool_size = (size_t)BOLT_RECV_POOL_COUNT * BOLT_RECV_BUF_SIZE;
    void *pool = nullptr;
    int cerr = posix_memalign(&pool, 4096, pool_size);
    if (cerr != 0 || !pool) {
        fprintf(stderr, "[BOLT GPU%d NIC%d] recv pool alloc failed\n", ctx->gpu_id, nic_idx);
        return -1;
    }
    memset(pool, 0, pool_size);
    ctx->recv[nic_idx].pool = pool;

    struct fid_mr *mr = nullptr;
    int ret = fi_mr_reg(ctx->domain, pool, pool_size,
                        FI_RECV, 0, 0x10000 + nic_idx, 0, &mr, nullptr);
    if (ret != 0) {
        fprintf(stderr, "[BOLT GPU%d NIC%d] recv MR reg failed: %d (%s)\n",
                ctx->gpu_id, nic_idx, ret, fi_strerror(-ret));
        free(pool);
        ctx->recv[nic_idx].pool = nullptr;
        return -1;
    }
    ctx->recv[nic_idx].mr = mr;
    ctx->recv[nic_idx].mr_desc = fi_mr_desc(mr);

    int posted = 0;
    for (int i = 0; i < BOLT_RECV_POOL_COUNT; i++) {
        bolt_recv_ctx *rctx = &ctx->recv[nic_idx].ctxs[i];
        memset(rctx, 0, sizeof(*rctx));
        rctx->buf_idx = i;
        rctx->nic_idx = nic_idx;

        struct iovec iov;
        iov.iov_base = (char*)pool + (size_t)i * BOLT_RECV_BUF_SIZE;
        iov.iov_len = BOLT_RECV_BUF_SIZE;
        void *desc = ctx->recv[nic_idx].mr_desc;

        struct fi_msg msg = {};
        msg.msg_iov = &iov;
        msg.desc = &desc;
        msg.iov_count = 1;
        msg.addr = FI_ADDR_UNSPEC;
        msg.context = &rctx->fi_ctx;

        ret = fi_recvmsg(ctx->nic[nic_idx].ep, &msg, 0);
        if (ret == 0) posted++;
        else if (posted == 0) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] fi_recvmsg[0] failed: %d (%s)\n",
                    ctx->gpu_id, nic_idx, ret, fi_strerror(-ret));
        }
    }
    fprintf(stderr, "[BOLT GPU%d NIC%d] Pre-posted %d/%d recv buffers (%d bytes each)\n",
            ctx->gpu_id, nic_idx, posted, BOLT_RECV_POOL_COUNT, BOLT_RECV_BUF_SIZE);
    return 0;
}

static int bolt_setup_notify_pool(bolt_context_t *ctx, int nic_idx) {
    size_t pool_size = (size_t)BOLT_NOTIFY_POOL_COUNT * sizeof(bolt_notify_msg);
    void *pool = nullptr;
    int cerr = posix_memalign(&pool, 4096, pool_size);
    if (cerr != 0 || !pool) {
        fprintf(stderr, "[BOLT GPU%d NIC%d] notify pool alloc failed\n", ctx->gpu_id, nic_idx);
        return -1;
    }
    memset(pool, 0, pool_size);
    ctx->notify[nic_idx].pool = pool;

    struct fid_mr *mr = nullptr;
    int ret = fi_mr_reg(ctx->domain, pool, pool_size,
                        FI_SEND, 0, 0x20000 + nic_idx, 0, &mr, nullptr);
    if (ret != 0) {
        fprintf(stderr, "[BOLT GPU%d NIC%d] notify MR reg failed: %d (%s)\n",
                ctx->gpu_id, nic_idx, ret, fi_strerror(-ret));
        free(pool);
        ctx->notify[nic_idx].pool = nullptr;
        return -1;
    }
    ctx->notify[nic_idx].mr = mr;
    ctx->notify[nic_idx].mr_desc = fi_mr_desc(mr);
    ctx->notify[nic_idx].next_free = 0;

    for (int i = 0; i < BOLT_NOTIFY_POOL_COUNT; i++) {
        ctx->notify[nic_idx].ctxs[i].buf_idx = i;
        ctx->notify[nic_idx].ctxs[i].active = false;
    }

    fprintf(stderr, "[BOLT GPU%d NIC%d] Notify pool ready (%d slots)\n",
            ctx->gpu_id, nic_idx, BOLT_NOTIFY_POOL_COUNT);
    return 0;
}

static int bolt_create_endpoints(bolt_context_t *ctx) {
    ctx->num_nics = 1;

    for (int n = 0; n < ctx->num_nics; n++) {
        struct fi_cq_attr cq_attr = {};
        cq_attr.size = 8192;
        cq_attr.format = FI_CQ_FORMAT_DATA;
        cq_attr.wait_obj = FI_WAIT_NONE;

        int ret = fi_cq_open(ctx->domain, &cq_attr, &ctx->nic[n].cq, nullptr);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] CQ open failed: %d\n", ctx->gpu_id, n, ret);
            return ret;
        }

        ret = fi_endpoint(ctx->domain, ctx->fi, &ctx->nic[n].ep, nullptr);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] EP create failed: %d\n", ctx->gpu_id, n, ret);
            return ret;
        }

        ret = fi_ep_bind(ctx->nic[n].ep, &ctx->nic[n].cq->fid,
                         FI_TRANSMIT | FI_RECV);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] EP bind CQ failed: %d (%s)\n",
                    ctx->gpu_id, n, ret, fi_strerror(-ret));
            return ret;
        }

        struct fi_av_attr av_attr = {};
        av_attr.type = FI_AV_TABLE;
        av_attr.count = BOLT_MAX_PEERS;

        ret = fi_av_open(ctx->domain, &av_attr, &ctx->nic[n].av, nullptr);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] AV open failed: %d\n", ctx->gpu_id, n, ret);
            return ret;
        }

        ret = fi_ep_bind(ctx->nic[n].ep, &ctx->nic[n].av->fid, 0);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] EP bind AV failed: %d\n", ctx->gpu_id, n, ret);
            return ret;
        }

        ret = fi_enable(ctx->nic[n].ep);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] EP enable failed: %d (%s)\n",
                    ctx->gpu_id, n, ret, fi_strerror(-ret));
            return ret;
        }

        ret = bolt_setup_recv_pool(ctx, n);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] recv pool setup failed\n", ctx->gpu_id, n);
        }

        ret = bolt_setup_notify_pool(ctx, n);
        if (ret) {
            fprintf(stderr, "[BOLT GPU%d NIC%d] notify pool setup failed\n", ctx->gpu_id, n);
        }

        fprintf(stderr, "[BOLT GPU%d NIC%d] Endpoint enabled (single CQ)\n", ctx->gpu_id, n);
    }

    return 0;
}

bolt_context_t* bolt_init(int gpu_id, int rank, int num_ranks,
                          void *gpu_buffer, size_t buffer_size) {
    fprintf(stderr, "[BOLT] Init GPU%d rank=%d/%d buf=%p size=%zuMB\n",
            gpu_id, rank, num_ranks, gpu_buffer, buffer_size / (1024*1024));

    auto *ctx = new bolt_context_t();
    memset(ctx, 0, sizeof(*ctx));
    new (&ctx->worker_running) std::atomic<bool>(false);
    new (&ctx->worker_thread) std::thread();

    ctx->gpu_id = gpu_id;
    ctx->rank = rank;
    ctx->num_ranks = num_ranks;
    ctx->num_rdma_ranks = num_ranks;
    ctx->gpu_buffer = gpu_buffer;
    ctx->buffer_size = buffer_size;

    ctx->fi = bolt_get_fi_info(gpu_id);
    if (!ctx->fi) {
        delete ctx;
        return nullptr;
    }
    ctx->msg_prefix_size = 0;

    int ret = fi_fabric(ctx->fi->fabric_attr, &ctx->fabric, nullptr);
    if (ret) {
        fprintf(stderr, "[BOLT GPU%d] fi_fabric failed: %d\n", gpu_id, ret);
        fi_freeinfo(ctx->fi);
        delete ctx;
        return nullptr;
    }

    ret = fi_domain(ctx->fabric, ctx->fi, &ctx->domain, nullptr);
    if (ret) {
        fprintf(stderr, "[BOLT GPU%d] fi_domain failed: %d\n", gpu_id, ret);
        fi_close(&ctx->fabric->fid);
        fi_freeinfo(ctx->fi);
        delete ctx;
        return nullptr;
    }

    ret = bolt_register_mr(ctx);
    if (ret) {
        fprintf(stderr, "[BOLT GPU%d] MR registration failed\n", gpu_id);
        fi_close(&ctx->domain->fid);
        fi_close(&ctx->fabric->fid);
        fi_freeinfo(ctx->fi);
        delete ctx;
        return nullptr;
    }

    ret = bolt_create_endpoints(ctx);
    if (ret) {
        fprintf(stderr, "[BOLT GPU%d] Endpoint creation failed\n", gpu_id);
        if (ctx->mr) fi_close(&ctx->mr->fid);
        fi_close(&ctx->domain->fid);
        fi_close(&ctx->fabric->fid);
        fi_freeinfo(ctx->fi);
        delete ctx;
        return nullptr;
    }

    cudaSetDevice(gpu_id);
    cudaMallocHost(&ctx->host_dispatch_signals,
                   BOLT_MAX_PEERS * sizeof(bolt_dispatch_signal_t));
    cudaMallocHost(&ctx->host_recv_signals,
                   BOLT_MAX_PEERS * sizeof(bolt_recv_signal_t));
    memset(ctx->host_dispatch_signals, 0,
           BOLT_MAX_PEERS * sizeof(bolt_dispatch_signal_t));
    memset(ctx->host_recv_signals, 0,
           BOLT_MAX_PEERS * sizeof(bolt_recv_signal_t));

    ctx->dispatch_signals = ctx->host_dispatch_signals;
    ctx->recv_signals = ctx->host_recv_signals;

    for (int i = 0; i < BOLT_MAX_PEERS; i++) {
        ctx->write_ctxs[i].active = false;
    }

    fprintf(stderr, "[BOLT GPU%d] Init complete. DMA-BUF=%s, NICs=%d\n",
            gpu_id, ctx->using_dmabuf ? "YES" : "NO (host-pinned)",
            ctx->num_nics);

    return ctx;
}

int bolt_get_local_info(bolt_context_t *ctx, bolt_fabric_info_t *info) {
    memset(info, 0, sizeof(*info));
    info->vaddr = (uint64_t)ctx->gpu_buffer;
    info->rkey = ctx->mr_key;
    info->num_nics = ctx->num_nics;

    size_t addrlen = sizeof(info->ep_name);
    int ret = fi_getname(&ctx->nic[0].ep->fid, info->ep_name, &addrlen);
    info->ep_name_len = (uint32_t)addrlen;
    if (ret) {
        fprintf(stderr, "[BOLT GPU%d] fi_getname failed: %d\n", ctx->gpu_id, ret);
        return ret;
    }

    fprintf(stderr, "[BOLT GPU%d] Local info: vaddr=0x%lx rkey=0x%lx ep_name_len=%u\n",
            ctx->gpu_id, (unsigned long)info->vaddr,
            (unsigned long)info->rkey, info->ep_name_len);
    return 0;
}

int bolt_apply_peers(bolt_context_t *ctx,
                     const bolt_fabric_info_t *all_info,
                     int num_ranks) {
    for (int r = 0; r < num_ranks; r++) {
        if (r == ctx->rank) continue;

        ctx->remote_vaddr[r] = all_info[r].vaddr;
        ctx->remote_rkey[r] = all_info[r].rkey;

        for (int n = 0; n < ctx->num_nics; n++) {
            fi_addr_t addr;
            int ret = fi_av_insert(ctx->nic[n].av,
                                   all_info[r].ep_name,
                                   1, &addr, 0, nullptr);
            if (ret != 1) {
                fprintf(stderr, "[BOLT GPU%d] AV insert rank %d NIC%d failed: ret=%d\n",
                        ctx->gpu_id, r, n, ret);
                continue;
            }
            ctx->nic[n].remote_addr[r] = addr;
            fprintf(stderr, "[BOLT GPU%d] Peer %d NIC%d: fi_addr=%ld vaddr=0x%lx rkey=0x%lx\n",
                    ctx->gpu_id, r, n, (long)addr,
                    (unsigned long)all_info[r].vaddr,
                    (unsigned long)all_info[r].rkey);
        }
    }
    return 0;
}

bolt_dispatch_signal_t* bolt_get_dispatch_signals(bolt_context_t *ctx) {
    return ctx->dispatch_signals;
}

bolt_recv_signal_t* bolt_get_recv_signals(bolt_context_t *ctx) {
    return ctx->recv_signals;
}

void bolt_destroy(bolt_context_t *ctx) {
    if (!ctx) return;

    ctx->worker_running.store(false, std::memory_order_release);
    if (ctx->worker_thread.joinable())
        ctx->worker_thread.join();

    for (int n = 0; n < ctx->num_nics; n++) {
        if (ctx->recv[n].mr) fi_close(&ctx->recv[n].mr->fid);
        if (ctx->recv[n].pool) free(ctx->recv[n].pool);
        if (ctx->notify[n].mr) fi_close(&ctx->notify[n].mr->fid);
        if (ctx->notify[n].pool) free(ctx->notify[n].pool);
    }

    if (ctx->mr) fi_close(&ctx->mr->fid);
    for (int n = 0; n < ctx->num_nics; n++) {
        if (ctx->nic[n].ep) fi_close(&ctx->nic[n].ep->fid);
        if (ctx->nic[n].cq) fi_close(&ctx->nic[n].cq->fid);
        if (ctx->nic[n].av) fi_close(&ctx->nic[n].av->fid);
    }
    if (ctx->domain) fi_close(&ctx->domain->fid);
    if (ctx->fabric) fi_close(&ctx->fabric->fid);
    if (ctx->fi) fi_freeinfo(ctx->fi);

    if (ctx->host_dispatch_signals) cudaFreeHost(ctx->host_dispatch_signals);
    if (ctx->host_recv_signals) cudaFreeHost(ctx->host_recv_signals);

    ctx->worker_thread.~thread();
    ctx->worker_running.~atomic();
    delete ctx;
}
```

## transport_worker.cpp

```cpp
#include "bolt_internal.h"

#include <cuda_runtime.h>
#include <cstdio>
#include <cstring>
#include <chrono>
#include <sched.h>
#include <pthread.h>

static void bolt_pin_worker(int gpu_id) {
    int numa_node = (gpu_id < 4) ? 0 : 1;
    int base_cpu = numa_node * 48;
    int target_cpu = base_cpu + 24 + gpu_id % 4;

    cpu_set_t cpuset;
    CPU_ZERO(&cpuset);
    CPU_SET(target_cpu, &cpuset);
    pthread_setaffinity_np(pthread_self(), sizeof(cpuset), &cpuset);

    struct sched_param param;
    memset(&param, 0, sizeof(param));
    param.sched_priority = 1;
    sched_setscheduler(0, SCHED_FIFO, &param);

    fprintf(stderr, "[BOLT-WORKER GPU%d] Pinned to CPU %d (NUMA %d)\n",
            gpu_id, target_cpu, numa_node);
}

static void bolt_repost_recv(bolt_context_t *ctx, int nic_idx, int buf_idx) {
    bolt_recv_ctx *rctx = &ctx->recv[nic_idx].ctxs[buf_idx];
    memset(&rctx->fi_ctx, 0, sizeof(rctx->fi_ctx));
    rctx->buf_idx = buf_idx;
    rctx->nic_idx = nic_idx;

    struct iovec iov;
    iov.iov_base = (char*)ctx->recv[nic_idx].pool + (size_t)buf_idx * BOLT_RECV_BUF_SIZE;
    iov.iov_len = BOLT_RECV_BUF_SIZE;
    void *desc = ctx->recv[nic_idx].mr_desc;

    struct fi_msg msg = {};
    msg.msg_iov = &iov;
    msg.desc = &desc;
    msg.iov_count = 1;
    msg.addr = FI_ADDR_UNSPEC;
    msg.context = &rctx->fi_ctx;

    ssize_t ret = fi_recvmsg(ctx->nic[nic_idx].ep, &msg, 0);
    if (ret != 0 && ret != -FI_EAGAIN) {
        static __thread int repost_err = 0;
        if (repost_err++ < 5)
            fprintf(stderr, "[BOLT-WORKER GPU%d NIC%d] repost recv[%d] failed: %zd (%s)\n",
                    ctx->gpu_id, nic_idx, buf_idx, ret, fi_strerror((int)-ret));
    }
}

static int bolt_send_notification(bolt_context_t *ctx, int nic_idx,
                                  int dest_rank, uint32_t num_tokens,
                                  uint32_t total_bytes) {
    auto &np = ctx->notify[nic_idx];
    int slot = -1;
    for (int i = 0; i < BOLT_NOTIFY_POOL_COUNT; i++) {
        int idx = (np.next_free + i) % BOLT_NOTIFY_POOL_COUNT;
        if (!np.ctxs[idx].active) {
            slot = idx;
            np.next_free = (idx + 1) % BOLT_NOTIFY_POOL_COUNT;
            break;
        }
    }
    if (slot < 0) {
        static __thread int notify_full = 0;
        if (notify_full++ < 5)
            fprintf(stderr, "[BOLT-WORKER GPU%d] Notify pool full!\n", ctx->gpu_id);
        return -1;
    }

    bolt_notify_msg *nmsg = (bolt_notify_msg*)np.pool + slot;
    nmsg->magic = BOLT_NOTIFY_MAGIC;
    nmsg->src_rank = (uint32_t)ctx->rank;
    nmsg->num_tokens = num_tokens;
    nmsg->total_bytes = total_bytes;

    np.ctxs[slot].active = true;
    np.ctxs[slot].buf_idx = slot;
    memset(&np.ctxs[slot].fi_ctx, 0, sizeof(np.ctxs[slot].fi_ctx));

    struct iovec iov;
    iov.iov_base = nmsg;
    iov.iov_len = sizeof(bolt_notify_msg);
    void *desc = np.mr_desc;

    struct fi_msg msg = {};
    msg.msg_iov = &iov;
    msg.desc = &desc;
    msg.iov_count = 1;
    msg.addr = ctx->nic[nic_idx].remote_addr[dest_rank];
    msg.context = &np.ctxs[slot].fi_ctx;

    ssize_t ret;
    int retries = 0;
    do {
        ret = fi_sendmsg(ctx->nic[nic_idx].ep, &msg, 0);
        if (ret == -FI_EAGAIN) {
            struct fi_cq_data_entry cqe[16];
            fi_cq_read(ctx->nic[nic_idx].cq, cqe, 16);
            retries++;
            if (retries > 500000) {
                fprintf(stderr, "[BOLT-WORKER GPU%d] fi_sendmsg stuck\n", ctx->gpu_id);
                np.ctxs[slot].active = false;
                return -1;
            }
        }
    } while (ret == -FI_EAGAIN);

    if (ret != 0) {
        fprintf(stderr, "[BOLT-WORKER GPU%d] fi_sendmsg failed: %zd (%s)\n",
                ctx->gpu_id, ret, fi_strerror((int)-ret));
        np.ctxs[slot].active = false;
        return (int)ret;
    }

    static __thread int notify_log = 0;
    if (notify_log++ < 8)
        fprintf(stderr, "[BOLT-NOTIFY GPU%d] Sent notify to rank %d: tokens=%u bytes=%u\n",
                ctx->gpu_id, dest_rank, num_tokens, total_bytes);

    return 0;
}

static int bolt_post_write(bolt_context_t *ctx, int dest_rank,
                           uint64_t src_offset, uint64_t dst_offset,
                           size_t length, uint32_t num_tokens) {
    int nic_idx = 0;

    static __thread int post_log = 0;
    if (post_log++ < 5)
        fprintf(stderr, "[BOLT-POST GPU%d] dest=%d len=%zu src=0x%lx dst=0x%lx\n",
                ctx->gpu_id, dest_rank, length,
                (unsigned long)src_offset, (unsigned long)dst_offset);

    uint64_t gpu_base = (uint64_t)ctx->gpu_buffer;
    uint64_t dst_rel = dst_offset - gpu_base;

    void *src = (void*)src_offset;
    uint64_t remote_base = ctx->remote_vaddr[dest_rank];
    uint64_t dst = remote_base + dst_rel;
    uint64_t rkey = ctx->remote_rkey[dest_rank];

    bolt_write_ctx *wctx = &ctx->write_ctxs[dest_rank];
    memset(&wctx->fi_ctx, 0, sizeof(wctx->fi_ctx));
    wctx->dest_rank = dest_rank;
    wctx->num_tokens = num_tokens;
    wctx->total_bytes = (uint32_t)length;
    wctx->active = true;

    struct iovec iov;
    iov.iov_base = src;
    iov.iov_len = length;
    void *desc = ctx->nic[nic_idx].mr_desc;
    struct fi_rma_iov rma_iov;
    rma_iov.addr = dst;
    rma_iov.len = length;
    rma_iov.key = rkey;

    struct fi_msg_rma msg = {};
    msg.msg_iov = &iov;
    msg.desc = &desc;
    msg.iov_count = 1;
    msg.addr = ctx->nic[nic_idx].remote_addr[dest_rank];
    msg.rma_iov = &rma_iov;
    msg.rma_iov_count = 1;
    msg.context = &wctx->fi_ctx;
    msg.data = 0;

    ssize_t ret;
    int retries = 0;
    do {
        ret = fi_writemsg(ctx->nic[nic_idx].ep, &msg, 0);
        if (ret == -FI_EAGAIN) {
            struct fi_cq_data_entry entries[32];
            fi_cq_read(ctx->nic[nic_idx].cq, entries, 32);
            retries++;
            if (retries > 1000000) {
                fprintf(stderr, "[BOLT-WORKER GPU%d] fi_writemsg EAGAIN stuck\n", ctx->gpu_id);
                wctx->active = false;
                return -1;
            }
        }
    } while (ret == -FI_EAGAIN);

    if (ret != 0) {
        fprintf(stderr, "[BOLT-WORKER GPU%d] fi_writemsg failed: %zd (%s) dest=%d len=%zu\n",
                ctx->gpu_id, ret, fi_strerror((int)-ret), dest_rank, length);
        wctx->active = false;
        return (int)ret;
    }

    static __thread int tx_log = 0;
    if (tx_log++ < 8) {
        fprintf(stderr, "[BOLT-TX GPU%d] fi_writemsg posted: dest=%d len=%zu fi_addr=%ld "
                "remote=0x%lx rkey=0x%lx\n",
                ctx->gpu_id, dest_rank, length,
                (long)ctx->nic[nic_idx].remote_addr[dest_rank],
                (unsigned long)dst, (unsigned long)rkey);
    }

    return 0;
}

static void bolt_poll_cq(bolt_context_t *ctx) {
    for (int n = 0; n < ctx->num_nics; n++) {
        struct fi_cq_data_entry cqe[32];

        ssize_t ret = fi_cq_read(ctx->nic[n].cq, cqe, 32);

        if (ret == -FI_EAVAIL) {
            struct fi_cq_err_entry err = {};
            fi_cq_readerr(ctx->nic[n].cq, &err, 0);
            static __thread int cq_err_log = 0;
            if (cq_err_log++ < 10)
                fprintf(stderr, "[BOLT-CQ GPU%d NIC%d] ERR: %s prov=%d flags=0x%lx\n",
                        ctx->gpu_id, n, fi_strerror(err.err), err.prov_errno,
                        (unsigned long)err.flags);

            if (err.flags & FI_WRITE) {
                bolt_write_ctx *wctx = (bolt_write_ctx*)err.op_context;
                if (wctx) wctx->active = false;
            }
            if (err.flags & FI_SEND) {
                bolt_send_ctx *sctx = (bolt_send_ctx*)err.op_context;
                if (sctx) sctx->active = false;
            }
            return;
        }

        if (ret <= 0) continue;

        for (int i = 0; i < (int)ret; i++) {
            uint64_t flags = cqe[i].flags;

            if (flags & FI_WRITE) {
                bolt_write_ctx *wctx = (bolt_write_ctx*)cqe[i].op_context;
                if (wctx && wctx->active) {
                    static __thread int write_done_log = 0;
                    if (write_done_log++ < 8)
                        fprintf(stderr, "[BOLT-CQ GPU%d] WRITE complete: dest=%d bytes=%u\n",
                                ctx->gpu_id, wctx->dest_rank, wctx->total_bytes);

                    bolt_send_notification(ctx, n, wctx->dest_rank,
                                           wctx->num_tokens, wctx->total_bytes);
                    wctx->active = false;
                }
            }

            if (flags & FI_SEND) {
                bolt_send_ctx *sctx = (bolt_send_ctx*)cqe[i].op_context;
                if (sctx) {
                    sctx->active = false;
                }
            }

            if (flags & FI_RECV) {
                bolt_recv_ctx *rctx = (bolt_recv_ctx*)cqe[i].op_context;
                if (rctx) {
                    void *buf = (char*)ctx->recv[rctx->nic_idx].pool +
                                (size_t)rctx->buf_idx * BOLT_RECV_BUF_SIZE;
                    bolt_notify_msg *nmsg = (bolt_notify_msg*)buf;

                    if (nmsg->magic == BOLT_NOTIFY_MAGIC) {
                        uint32_t src_rank = nmsg->src_rank;
                        if (src_rank < (uint32_t)BOLT_MAX_PEERS) {
                            ctx->host_recv_signals[src_rank].num_tokens = nmsg->num_tokens;
                            ctx->host_recv_signals[src_rank].total_bytes = nmsg->total_bytes;
                            __atomic_store_n(&ctx->host_recv_signals[src_rank].ready, 1,
                                             __ATOMIC_RELEASE);

                            static __thread int recv_notify_log = 0;
                            if (recv_notify_log++ < 8)
                                fprintf(stderr, "[BOLT-CQ GPU%d] RECV notify from rank %u: "
                                        "tokens=%u bytes=%u\n",
                                        ctx->gpu_id, src_rank,
                                        nmsg->num_tokens, nmsg->total_bytes);
                        }
                    } else {
                        static __thread int recv_other_log = 0;
                        if (recv_other_log++ < 5)
                            fprintf(stderr, "[BOLT-CQ GPU%d] RECV non-notify msg len=%zu flags=0x%lx\n",
                                    ctx->gpu_id, cqe[i].len, (unsigned long)flags);
                    }

                    bolt_repost_recv(ctx, rctx->nic_idx, rctx->buf_idx);
                }
            }

            if (flags & FI_REMOTE_WRITE) {
                static __thread int rw_log = 0;
                if (rw_log++ < 3)
                    fprintf(stderr, "[BOLT-CQ GPU%d] FI_REMOTE_WRITE (unexpected)\n",
                            ctx->gpu_id);
            }
        }
    }
}

static void bolt_worker_loop(bolt_context_t *ctx) {
    bolt_pin_worker(ctx->gpu_id);

    cudaError_t cerr = cudaSetDevice(ctx->gpu_id);
    if (cerr != cudaSuccess) {
        fprintf(stderr, "[BOLT-WORKER GPU%d] FATAL: cudaSetDevice failed: %s\n",
                ctx->gpu_id, cudaGetErrorString(cerr));
        return;
    }

    cudaStream_t stream;
    cerr = cudaStreamCreateWithFlags(&stream, cudaStreamNonBlocking);
    if (cerr != cudaSuccess) {
        fprintf(stderr, "[BOLT-WORKER GPU%d] FATAL: cudaStreamCreate failed: %s\n",
                ctx->gpu_id, cudaGetErrorString(cerr));
        return;
    }
    ctx->cuda_stream = (void*)stream;

    fprintf(stderr, "[BOLT-WORKER GPU%d] Worker started (rank=%d, peers=%d)\n",
            ctx->gpu_id, ctx->rank, ctx->num_rdma_ranks);

    uint64_t iter = 0;
    while (ctx->worker_running.load(std::memory_order_relaxed)) {
        bool did_work = false;

        for (int dest = 0; dest < ctx->num_ranks; dest++) {
            if (dest == ctx->rank) continue;

            uint8_t ready = __atomic_load_n(
                &ctx->host_dispatch_signals[dest].ready, __ATOMIC_ACQUIRE);
            if (!ready) continue;

            uint32_t num_tokens = ctx->host_dispatch_signals[dest].num_tokens;
            uint32_t total_bytes = ctx->host_dispatch_signals[dest].total_bytes;
            uint64_t src_off = ctx->host_dispatch_signals[dest].src_offset;
            uint64_t dst_off = ctx->host_dispatch_signals[dest].dst_offset;

            static __thread int dispatch_log = 0;
            if (dispatch_log++ < 8) {
                fprintf(stderr, "[BOLT-WORKER GPU%d] Dispatch to rank %d: "
                        "%u tokens, %u bytes, src=0x%lx dst=0x%lx\n",
                        ctx->gpu_id, dest, num_tokens, total_bytes,
                        (unsigned long)src_off, (unsigned long)dst_off);
            }

            int ret = bolt_post_write(ctx, dest, src_off, dst_off,
                                      total_bytes, num_tokens);
            if (ret == 0) {
                __atomic_store_n(&ctx->host_dispatch_signals[dest].ready, 0,
                                 __ATOMIC_RELEASE);
            }

            did_work = true;
        }

        bolt_poll_cq(ctx);

        if (!did_work) {
            for (int i = 0; i < 8; i++)
                __builtin_ia32_pause();
        }

        iter++;

        if ((iter & 0xFFFF) == 0) {
            bolt_poll_cq(ctx);
        }
    }

    if (ctx->cuda_stream) {
        cudaStreamDestroy((cudaStream_t)ctx->cuda_stream);
        ctx->cuda_stream = nullptr;
    }

    fprintf(stderr, "[BOLT-WORKER GPU%d] Worker stopped after %lu iterations\n",
            ctx->gpu_id, (unsigned long)iter);
}

int bolt_start_worker(bolt_context_t *ctx) {
    ctx->worker_running.store(true, std::memory_order_release);
    ctx->worker_thread = std::thread(bolt_worker_loop, ctx);
    return 0;
}

int bolt_wait_dispatch_complete(bolt_context_t *ctx, int timeout_ms) {
    auto start = std::chrono::steady_clock::now();
    while (true) {
        bool all_done = true;
        for (int dest = 0; dest < ctx->num_ranks; dest++) {
            if (dest == ctx->rank) continue;
            if (__atomic_load_n(&ctx->host_dispatch_signals[dest].ready,
                                __ATOMIC_ACQUIRE)) {
                all_done = false;
                break;
            }
        }
        if (all_done) return 0;

        if (timeout_ms > 0) {
            auto elapsed = std::chrono::steady_clock::now() - start;
            if (std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count()
                >= timeout_ms)
                return -1;
        }
        __builtin_ia32_pause();
    }
}

int bolt_wait_recv_complete(bolt_context_t *ctx,
                            uint32_t expected_sources,
                            int timeout_ms) {
    auto start = std::chrono::steady_clock::now();
    uint32_t received = 0;
    while (received != expected_sources) {
        for (int src = 0; src < ctx->num_ranks; src++) {
            if (!(expected_sources & (1u << src))) continue;
            if (received & (1u << src)) continue;
            if (__atomic_load_n(&ctx->host_recv_signals[src].ready,
                                __ATOMIC_ACQUIRE)) {
                received |= (1u << src);
            }
        }
        if (timeout_ms > 0) {
            auto elapsed = std::chrono::steady_clock::now() - start;
            if (std::chrono::duration_cast<std::chrono::milliseconds>(elapsed).count()
                >= timeout_ms) {
                fprintf(stderr, "[BOLT-WORKER GPU%d] recv timeout: got 0x%x, expected 0x%x\n",
                        ctx->gpu_id, received, expected_sources);
                return -1;
            }
        }
        __builtin_ia32_pause();
    }
    return 0;
}
```