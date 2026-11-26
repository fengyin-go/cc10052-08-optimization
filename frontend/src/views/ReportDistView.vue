<template>
  <section class="page" data-module="report_dist">
    <header class="page-head">
      <div>
        <h2>报告分发 · 续做工作台</h2>
        <p class="page-desc">
          按报告版次查看收件名单与续做清单；只处理确实未送达的收件人，已签收材料不重复投递。
        </p>
      </div>
      <div class="page-actions">
        <button class="btn" type="button" @click="openProxyModal()">登记代领资格</button>
      </div>
    </header>

    <div class="stat-row">
      <article class="stat-card">
        <span class="stat-label">待续做收件人</span>
        <strong class="stat-value">{{ continuation.待续做人数 ?? 0 }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">当前版次有效签收</span>
        <strong class="stat-value">{{ receipts.length }}</strong>
      </article>
      <article class="stat-card">
        <span class="stat-label">代领资格（生效/沿革）</span>
        <strong class="stat-value">{{ proxies.length }}</strong>
      </article>
    </div>

    <form class="filter-bar" @submit.prevent="reload">
      <label class="filter-item">
        <span>报告版次</span>
        <input v-model="versionFilter" data-testid="filter-version" placeholder="如 R-v2" />
      </label>
      <label class="filter-item">
        <span>分发批次</span>
        <input v-model="batchFilter" data-testid="filter-batch" placeholder="按批次过滤" />
      </label>
      <button class="btn primary" data-testid="query" type="submit">查询续做清单</button>
      <button class="btn ghost" type="button" @click="resetFilters">重置</button>
    </form>

    <h3 class="section-title">分发续做清单（仅未送达）</h3>
    <table class="data-table" data-testid="continuation-table">
      <thead>
        <tr>
          <th>选择</th>
          <th>报告版次</th>
          <th>分发批次</th>
          <th>接收方</th>
          <th>分发渠道</th>
          <th>当前状态</th>
          <th>未送达原因</th>
          <th>本人地址</th>
          <th>生效代领人</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr
          v-for="item in continuation.items ?? []"
          :key="item.id"
          :data-testid="`cont-row-${item.id}`"
          :data-status="item.当前状态"
        >
          <td><input v-model="selectedIds" type="checkbox" :value="item.id" /></td>
          <td>{{ item.报告版次 }}</td>
          <td>{{ item.分发批次 }}</td>
          <td>{{ item.接收方 }}</td>
          <td>{{ item.分发渠道 }}</td>
          <td><span class="badge" :class="badgeClass(item.当前状态)">{{ item.当前状态 }}</span></td>
          <td>{{ item.失败原因 || '—' }}</td>
          <td>{{ item.本人地址有效 ? '有效' : '失效' }}</td>
          <td>{{ item.可代领人 || '—' }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openDetail(item.id)">投递详情</button>
            <button
              v-if="item.当前状态 !== '续做中'"
              class="link"
              type="button"
              @click="applyContinuation(item.id)"
            >
              办理续做
            </button>
            <button class="link" type="button" @click="openDeliverModal(item)">续做送达</button>
          </td>
        </tr>
        <tr v-if="!(continuation.items && continuation.items.length)">
          <td colspan="10" class="empty-state">该版次没有待续做收件人，全部送达或尚未登记分发</td>
        </tr>
      </tbody>
    </table>
    <div class="page-actions" style="margin: 10px 0">
      <button
        class="btn primary"
        data-testid="batch-deliver"
        type="button"
        :disabled="!selectedIds.length"
        @click="onBatchDeliver"
      >
        批量续做送达（{{ selectedIds.length }}）
      </button>
    </div>

    <h3 class="section-title">有效签收回执（同版次+接收方+渠道唯一）</h3>
    <table class="data-table" data-testid="receipt-table">
      <thead>
        <tr>
          <th>报告版次</th>
          <th>分发批次</th>
          <th>接收方</th>
          <th>分发渠道</th>
          <th>实际签收人</th>
          <th>是否代领</th>
          <th>使用代领资格</th>
          <th>送达时间</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="receipt in receipts" :key="receipt.id" :data-testid="`receipt-row-${receipt.id}`">
          <td>{{ receipt.报告版次 }}</td>
          <td>{{ receipt.分发批次 }}</td>
          <td>{{ receipt.接收方 }}</td>
          <td>{{ receipt.分发渠道 }}</td>
          <td><strong>{{ receipt.实际签收人 }}</strong></td>
          <td>
            <span :class="receipt.是否代领 ? 'badge warn' : 'badge ok'">
              {{ receipt.是否代领 ? '代领' : '本人' }}
            </span>
          </td>
          <td>{{ receipt.使用代领资格 || '—' }}</td>
          <td>{{ formatTime(receipt.送达时间) }}</td>
        </tr>
        <tr v-if="!receipts.length">
          <td colspan="8" class="empty-state">暂无有效签收</td>
        </tr>
      </tbody>
    </table>

    <h3 class="section-title">代领资格沿革（撤换/实际使用可追溯）</h3>
    <table class="data-table" data-testid="proxy-table">
      <thead>
        <tr>
          <th>资格编号</th>
          <th>报告版次</th>
          <th>接收方</th>
          <th>代领人</th>
          <th>资格状态</th>
          <th>登记时间</th>
          <th>撤换时间</th>
          <th>实际使用回执</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="proxy in proxies" :key="proxy.id" :data-testid="`proxy-row-${proxy.id}`">
          <td>{{ proxy.资格编号 }}</td>
          <td>{{ proxy.报告版次 }}</td>
          <td>{{ proxy.接收方 }}</td>
          <td>{{ proxy.代领人 }}</td>
          <td><span class="badge" :class="badgeClass(proxy.资格状态)">{{ proxy.资格状态 }}</span></td>
          <td>{{ formatTime(proxy.登记时间) }}</td>
          <td>{{ formatTime(proxy.撤换时间) || '—' }}</td>
          <td>{{ proxy.使用回执 || '—' }}</td>
        </tr>
      </tbody>
    </table>

    <!-- 投递详情：可续办 / 已签收分开 -->
    <div v-if="detail" class="modal-backdrop" data-testid="detail-modal" @click.self="detail = null">
      <div class="modal wide">
        <h3>投递详情 · {{ detail.entry.接收方 }}（{{ detail.entry.报告版次 }}）</h3>

        <h4 class="subsection">可续办区（未送达）</h4>
        <div v-if="detail.未送达区" class="detail-box pending">
          <p>当前状态：<strong>{{ detail.未送达区.当前状态 }}</strong>｜续做次数：{{ detail.未送达区.续做次数 }}</p>
          <p>未送达原因：{{ detail.未送达区.失败原因 || '—' }}</p>
          <p>
            本人地址：{{ detail.未送达区.本人地址有效 ? '仍有效' : '已失效' }} ｜
            续做意向：{{ detail.未送达区.续做意向 || '—' }}
          </p>
          <p>
            生效代领资格：{{ detail.未送达区.生效代领资格 || '无' }} ｜
            可代领人：{{ detail.未送达区.可代领人 || '—' }}
          </p>
        </div>
        <div v-else class="detail-box done">该收件人已完成送达，无需续办。</div>

        <h4 class="subsection">已签收区（有效回执）</h4>
        <table v-if="detail.已签收区.length" class="data-table">
          <thead>
            <tr><th>回执编号</th><th>渠道</th><th>实际签收人</th><th>代领</th><th>使用资格</th><th>送达时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="r in detail.已签收区" :key="r.回执编号">
              <td>{{ r.回执编号 }}</td>
              <td>{{ r.分发渠道 }}</td>
              <td><strong>{{ r.实际签收人 }}</strong></td>
              <td>{{ r.是否代领 ? '代领' : '本人' }}</td>
              <td>{{ r.使用代领资格 || '—' }}</td>
              <td>{{ formatTime(r.送达时间) }}</td>
            </tr>
          </tbody>
        </table>
        <p v-else class="empty-state">暂无有效签收</p>

        <h4 class="subsection">代领资格沿革</h4>
        <table class="data-table">
          <thead>
            <tr><th>资格编号</th><th>代领人</th><th>状态</th><th>撤换时间</th><th>使用回执</th></tr>
          </thead>
          <tbody>
            <tr v-for="p in detail.代领资格沿革" :key="p.资格编号">
              <td>{{ p.资格编号 }}</td>
              <td>{{ p.代领人 }}</td>
              <td>{{ p.资格状态 }}</td>
              <td>{{ formatTime(p.撤换时间) || '—' }}</td>
              <td>{{ p.使用回执 || '—' }}</td>
            </tr>
            <tr v-if="!detail.代领资格沿革.length"><td colspan="5" class="empty-state">无代领资格登记</td></tr>
          </tbody>
        </table>

        <div class="page-actions" style="margin-top: 12px">
          <button class="btn ghost" type="button" @click="detail = null">关闭</button>
        </div>
      </div>
    </div>

    <!-- 续做送达：本人继续办理 vs 代领冲突选择 -->
    <div v-if="deliverTarget" class="modal-backdrop" data-testid="deliver-modal" @click.self="deliverTarget = null">
      <form class="modal" @submit.prevent="confirmDeliver">
        <h3>续做送达 · {{ deliverTarget.接收方 }}（{{ deliverTarget.报告版次 }}）</h3>
        <p class="page-desc">
          当前渠道：{{ deliverTarget.分发渠道 }} ｜ 状态：{{ deliverTarget.当前状态 }}
          <template v-if="deliverTarget.可代领人"> ｜ 生效代领人：{{ deliverTarget.可代领人 }}</template>
        </p>
        <label class="create-field">
          <span>续做渠道（可切换后再送达）</span>
          <select v-model="deliverChannel" data-testid="deliver-channel">
            <option value="站内信">站内信</option>
            <option value="邮件">邮件</option>
            <option value="webhook">webhook</option>
          </select>
        </label>
        <label class="create-field">
          <span>实际接件人（本人继续办理与代领资格冲突时在此明确）</span>
          <select v-model="deliverChoice" data-testid="deliver-choice">
            <option value="auto">按生效资格自动判定</option>
            <option value="self">本人继续办理（本人地址有效时）</option>
            <option value="proxy">由代领人签收（需生效代领资格）</option>
          </select>
        </label>
        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="deliverTarget = null">取消</button>
          <button class="btn primary" data-testid="confirm-deliver" type="submit">确认送达</button>
        </div>
      </form>
    </div>

    <!-- 登记/撤换代领资格 -->
    <div v-if="proxyModal" class="modal-backdrop" data-testid="proxy-modal" @click.self="proxyModal = false">
      <form class="modal" @submit.prevent="submitProxy">
        <h3>登记 / 撤换代领资格</h3>
        <label class="create-field">
          <span>报告版次</span>
          <input v-model="proxyForm.report_version" data-testid="proxy-version" required placeholder="如 R-v2" />
        </label>
        <label class="create-field">
          <span>接收方</span>
          <input v-model="proxyForm.receiver" data-testid="proxy-receiver" required placeholder="如 评审员B" />
        </label>
        <label class="create-field">
          <span>代领人</span>
          <input v-model="proxyForm.proxy_person" data-testid="proxy-person" required placeholder="如 协作评审员C" />
        </label>
        <label class="create-field">
          <span>已有生效资格时</span>
          <select v-model="proxyForm.replace" data-testid="proxy-replace">
            <option :value="false">保留（同人重复登记将忽略）</option>
            <option :value="true">撤换旧资格并启用新资格</option>
          </select>
        </label>
        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        <div class="page-actions">
          <button class="btn" type="button" @click="proxyModal = false">取消</button>
          <button class="btn primary" data-testid="submit-proxy" type="submit">保存资格</button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>{{ message || '续做不新建投递；同一版次、接收方、渠道只保留一份有效签收' }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import {
  batchDeliver,
  deliverEntry,
  fetchContinuationList,
  fetchDeliveryDetail,
  fetchProxies,
  fetchValidReceipts,
  registerContinuation,
  registerProxy,
  switchChannel,
  type ContinuationItem,
  type DeliveryDetail,
  type Proxy,
  type Receipt,
} from '@/api/report-workflow'

const versionFilter = ref('R-v2')
const batchFilter = ref('')
const selectedIds = ref<number[]>([])
const continuation = ref<Partial<{ 待续做人数: number; items: ContinuationItem[] }>>({})
const receipts = ref<Receipt[]>([])
const proxies = ref<Proxy[]>([])
const detail = ref<DeliveryDetail | null>(null)
const deliverTarget = ref<ContinuationItem | null>(null)
const deliverChoice = ref<'auto' | 'self' | 'proxy'>('auto')
const deliverChannel = ref('邮件')
const proxyModal = ref(false)
const proxyForm = ref({ report_version: 'R-v2', receiver: '', proxy_person: '', replace: false })
const message = ref('')
const errorMessage = ref('')

function badgeClass(status: string): string {
  if (status === '已送达' || status === '生效') return 'ok'
  if (status === '已拒收' || status === '送达失败' || status === '已撤换') return 'danger'
  if (status === '续做中' || status === '已使用') return 'warn'
  return ''
}

function formatTime(value: string): string {
  if (!value) return ''
  return value.replace('T', ' ').replace(/\+.*$/, '')
}

async function reload() {
  errorMessage.value = ''
  try {
    const [cont, receiptResp, proxyResp] = await Promise.all([
      fetchContinuationList(versionFilter.value.trim(), batchFilter.value.trim()),
      fetchValidReceipts(versionFilter.value.trim()),
      fetchProxies(versionFilter.value.trim()),
    ])
    continuation.value = cont.data ?? {}
    receipts.value = receiptResp.data ?? []
    proxies.value = proxyResp.data ?? []
    selectedIds.value = []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '续做清单读取失败'
  }
}

function resetFilters() {
  versionFilter.value = ''
  batchFilter.value = ''
  void reload()
}

async function applyContinuation(id: number) {
  errorMessage.value = ''
  try {
    const result = await registerContinuation(id)
    message.value = result.message
    if (!result.ok) errorMessage.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '续做登记失败'
  }
}

async function openDetail(id: number) {
  errorMessage.value = ''
  try {
    const result = await fetchDeliveryDetail(id)
    detail.value = result.data ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '详情读取失败'
  }
}

function openDeliverModal(item: ContinuationItem) {
  deliverTarget.value = item
  deliverChoice.value = 'auto'
  deliverChannel.value = item.分发渠道 || '邮件'
  errorMessage.value = ''
}

async function confirmDeliver() {
  if (!deliverTarget.value) return
  try {
    if (deliverChannel.value !== deliverTarget.value.分发渠道) {
      const switched = await switchChannel(deliverTarget.value.id, deliverChannel.value)
      if (!switched.ok) {
        errorMessage.value = switched.message
        return
      }
    }
    const useProxy = deliverChoice.value === 'auto' ? null : deliverChoice.value === 'proxy'
    const result = await deliverEntry(deliverTarget.value.id, useProxy)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    message.value = result.message
    deliverTarget.value = null
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '续做送达失败'
  }
}

async function onBatchDeliver() {
  errorMessage.value = ''
  try {
    const result = await batchDeliver(selectedIds.value)
    message.value = result.message
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '批量续做失败'
  }
}

function openProxyModal() {
  proxyForm.value = { report_version: versionFilter.value || 'R-v2', receiver: '', proxy_person: '', replace: false }
  proxyModal.value = true
  errorMessage.value = ''
}

async function submitProxy() {
  try {
    const result = await registerProxy(proxyForm.value)
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    message.value = result.message
    proxyModal.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '代领资格保存失败'
  }
}

onMounted(reload)
</script>

<style scoped>
.section-title { font-size: 15px; margin: 18px 0 8px; }
.subsection { font-size: 13px; margin: 12px 0 6px; color: var(--muted); }
.modal.wide { width: min(880px, 100%); }
.detail-box { border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; font-size: 13px; }
.detail-box.pending { background: #fff7ed; border-color: #fdba74; }
.detail-box.done { background: #f0fdf4; border-color: #86efac; }
.detail-box p { margin: 4px 0; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #e2e8f0; }
.badge.ok { background: #dcfce7; color: #166534; }
.badge.warn { background: #fef3c7; color: #92400e; }
.badge.danger { background: #fee2e2; color: #991b1b; }
select { padding: 8px; border: 1px solid var(--border); border-radius: 6px; width: 100%; }
</style>
