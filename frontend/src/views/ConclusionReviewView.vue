<template>
  <section class="page" data-module="conclusion_review">
    <header class="page-head">
      <div>
        <h2>结论评审队列 · 证据领用</h2>
        <p class="page-desc">
          评审人员从对应报告版次选择已送达证据并领用签收，不必等整组全部完成；证据按版本列出实际送达的人。
        </p>
      </div>
    </header>

    <form class="filter-bar" @submit.prevent="loadEvidence">
      <label class="filter-item">
        <span>报告编码（可选）</span>
        <input v-model="reportCode" data-testid="review-report-code" placeholder="如 RPT-R-V2" />
      </label>
      <button class="btn primary" data-testid="review-query" type="submit">刷新版次证据</button>
    </form>

    <h3 class="section-title">按报告版次的有效送达证据（实际复核依据）</h3>
    <div v-for="group in evidenceGroups" :key="group.报告版次" class="evidence-card" data-testid="evidence-card">
      <div class="evidence-head">
        <strong>版次 {{ group.报告版次 }}</strong>
        <span class="page-desc">报告 {{ group.报告编码 }} ｜ 有效签收 {{ group.有效签收数 }} 份 ｜ 批次 {{ group.投递批次.join('、') }}</span>
        <button class="btn" type="button" @click="openClaim(group.报告版次)">领用此版次证据</button>
      </div>
      <table class="data-table">
        <thead>
          <tr>
            <th>接收方</th>
            <th>实际签收人</th>
            <th>渠道</th>
            <th>签收方式</th>
            <th>使用代领资格</th>
            <th>分发批次</th>
            <th>送达时间</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="person in group.实际送达的人" :key="person.回执编号" :data-testid="`evidence-row-${person.回执编号}`">
            <td>{{ person.接收方 }}</td>
            <td><strong>{{ person.实际签收人 }}</strong></td>
            <td>{{ person.分发渠道 }}</td>
            <td>
              <span :class="person.是否代领 ? 'badge warn' : 'badge ok'">
                {{ person.是否代领 ? '代领签收' : '本人签收' }}
              </span>
            </td>
            <td>{{ person.使用代领资格 || '—' }}</td>
            <td>{{ person.分发批次 }}</td>
            <td>{{ formatTime(person.送达时间) }}</td>
          </tr>
        </tbody>
      </table>
    </div>
    <p v-if="!evidenceGroups.length" class="empty-state">暂无有效签收证据，等待报告分发送达</p>

    <h3 class="section-title">评审记录与已领证据</h3>
    <table class="data-table" data-testid="review-table">
      <thead>
        <tr>
          <th>记录编号</th>
          <th>实验编码</th>
          <th>评审结论</th>
          <th>当前状态</th>
          <th>证据版次</th>
          <th>已领证据数</th>
          <th>操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in reviews" :key="String(row.id)" :data-testid="`review-row-${row.id}`" :data-status="String(row.status)">
          <td>{{ row.记录编号 }}</td>
          <td>{{ row.实验编码 }}</td>
          <td>{{ row.评审结论 }}</td>
          <td><span class="badge" :class="badgeClass(String(row.status))">{{ row.status }}</span></td>
          <td>{{ row.证据版次 || '—' }}</td>
          <td>{{ Array.isArray(row.已领证据) ? row.已领证据.length : 0 }}</td>
          <td class="row-actions">
            <button class="link" type="button" @click="openEvidenceDetail(Number(row.id))">证据明细</button>
            <button
              v-if="row.status === '待评审'"
              class="link"
              type="button"
              @click="openClaim('', Number(row.id))"
            >
              领用签收
            </button>
            <button
              v-if="row.status === '待评审'"
              class="link"
              type="button"
              @click="onApprove(Number(row.id))"
            >
              复核通过
            </button>
          </td>
        </tr>
      </tbody>
    </table>

    <!-- 领用签收弹窗 -->
    <div v-if="claimModal" class="modal-backdrop" data-testid="claim-modal" @click.self="claimModal = false">
      <form class="modal wide" @submit.prevent="confirmClaim">
        <h3>领用送达证据 · {{ claimForm.report_version }}</h3>
        <p class="page-desc">只可领用该版次的有效签收；同一回执在本评审记录中只能领用一次。</p>
        <label class="create-field">
          <span>评审记录</span>
          <select v-model="claimForm.entry_id" data-testid="claim-entry" required>
            <option v-for="row in reviews.filter((r) => r.status === '待评审')" :key="row.id" :value="Number(row.id)">
              {{ row.记录编号 }}｜{{ row.评审结论 }}
            </option>
          </select>
        </label>
        <label class="create-field">
          <span>领用评审员</span>
          <input v-model="claimForm.reviewer" data-testid="claim-reviewer" placeholder="值班评审员" />
        </label>
        <table class="data-table">
          <thead>
            <tr><th>选择</th><th>回执编号</th><th>接收方</th><th>实际签收人</th><th>渠道</th><th>代领</th></tr>
          </thead>
          <tbody>
            <tr v-for="receipt in availableItems" :key="receipt.id">
              <td><input v-model="claimReceiptIds" type="checkbox" :value="receipt.id" /></td>
              <td>{{ receipt.回执编号 }}</td>
              <td>{{ receipt.接收方 }}</td>
              <td><strong>{{ receipt.实际签收人 }}</strong></td>
              <td>{{ receipt.分发渠道 }}</td>
              <td>{{ receipt.是否代领 ? '代领' : '本人' }}</td>
            </tr>
            <tr v-if="!availableItems.length">
              <td colspan="6" class="empty-state">该版次暂无可领用回执</td>
            </tr>
          </tbody>
        </table>
        <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>
        <div class="page-actions" style="margin-top: 10px">
          <button class="btn" type="button" @click="claimModal = false">取消</button>
          <button class="btn primary" data-testid="confirm-claim" type="submit" :disabled="!claimReceiptIds.length">
            领用选中（{{ claimReceiptIds.length }}）
          </button>
        </div>
      </form>
    </div>

    <!-- 证据明细弹窗：按版本列出实际送达的人 -->
    <div v-if="evidenceDetail" class="modal-backdrop" data-testid="evidence-detail-modal" @click.self="evidenceDetail = null">
      <div class="modal wide">
        <h3>评审证据明细 · {{ evidenceDetail.记录编号 }}（{{ evidenceDetail.评审状态 }}）</h3>
        <div v-for="group in evidenceDetail.按版次证据" :key="group.报告版次" class="evidence-card">
          <h4 class="subsection">报告版次：{{ group.报告版次 }}</h4>
          <table class="data-table">
            <thead>
              <tr><th>回执编号</th><th>接收方</th><th>实际签收人</th><th>渠道</th><th>代领</th><th>领用评审员</th><th>领用时间</th></tr>
            </thead>
            <tbody>
              <tr v-for="item in group.实际送达的人" :key="String(item.回执编号)">
                <td>{{ item.回执编号 }}</td>
                <td>{{ item.接收方 }}</td>
                <td><strong>{{ item.实际签收人 }}</strong></td>
                <td>{{ item.分发渠道 }}</td>
                <td>{{ item.是否代领 ? '代领' : '本人' }}</td>
                <td>{{ item.领用评审员 }}</td>
                <td>{{ formatTime(String(item.领用时间)) }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-if="!evidenceDetail.按版次证据.length" class="empty-state">尚未领用任何证据</p>
        <div class="page-actions" style="margin-top: 12px">
          <button class="btn ghost" type="button" @click="evidenceDetail = null">关闭</button>
        </div>
      </div>
    </div>

    <footer class="page-foot">
      <span>{{ message || '只有实际签收人的有效回执可作为本轮评审证据；不同版次分别查证' }}</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'

import { listEntries } from '@/api/backend-service'
import {
  approveReview,
  claimEvidence,
  fetchAvailableEvidence,
  fetchEvidenceVersions,
  fetchReviewEvidence,
  type Receipt,
  type ReviewEvidenceDetail,
  type VersionEvidence,
} from '@/api/report-workflow'
import type { EntryRow } from '@/data/types'

const reportCode = ref('')
const evidenceGroups = ref<VersionEvidence[]>([])
const reviews = ref<EntryRow[]>([])
const claimModal = ref(false)
const claimForm = ref({ entry_id: 0, report_version: '', reviewer: '' })
const claimReceiptIds = ref<number[]>([])
const availableItems = ref<Receipt[]>([])
const evidenceDetail = ref<ReviewEvidenceDetail | null>(null)
const message = ref('')
const errorMessage = ref('')

function badgeClass(status: string): string {
  if (status === '已通过') return 'ok'
  if (status === '已驳回') return 'danger'
  return 'warn'
}

function formatTime(value: string): string {
  if (!value) return ''
  return value.replace('T', ' ').replace(/\+.*$/, '')
}

async function loadReviews() {
  const payload = await listEntries('conclusion_review', {})
  reviews.value = payload.items
}

async function loadEvidence() {
  errorMessage.value = ''
  try {
    const result = await fetchEvidenceVersions(reportCode.value.trim())
    evidenceGroups.value = result.data ?? []
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '版次证据读取失败'
  }
}

async function openClaim(version: string, presetEntryId = 0) {
  errorMessage.value = ''
  claimForm.value = {
    entry_id: presetEntryId || reviews.value.find((r) => r.status === '待评审')?.id as number || 0,
    report_version: version,
    reviewer: '',
  }
  claimReceiptIds.value = []
  availableItems.value = []
  claimModal.value = true
  if (version) {
    const result = await fetchAvailableEvidence(version)
    availableItems.value = result.data?.items ?? []
  }
}

async function confirmClaim() {
  errorMessage.value = ''
  try {
    for (const receiptId of claimReceiptIds.value) {
      const result = await claimEvidence(claimForm.value.entry_id, {
        report_version: claimForm.value.report_version,
        receipt_id: receiptId,
        reviewer: claimForm.value.reviewer || '值班评审员',
      })
      if (!result.ok) {
        errorMessage.value = result.message
        return
      }
    }
    message.value = `已领用 ${claimReceiptIds.value.length} 份 ${claimForm.value.report_version} 有效回执`
    claimModal.value = false
    await Promise.all([loadReviews(), loadEvidence()])
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证据领用失败'
  }
}

async function openEvidenceDetail(entryId: number) {
  errorMessage.value = ''
  try {
    const result = await fetchReviewEvidence(entryId)
    evidenceDetail.value = result.data ?? null
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '证据明细读取失败'
  }
}

async function onApprove(entryId: number) {
  errorMessage.value = ''
  try {
    const result = await approveReview(entryId, '按投递批次采纳当前版次真实回执')
    if (!result.ok) {
      errorMessage.value = result.message
      return
    }
    message.value = result.message
    await loadReviews()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '评审通过失败'
  }
}

onMounted(async () => {
  await Promise.all([loadReviews(), loadEvidence()])
})
</script>

<style scoped>
.section-title { font-size: 15px; margin: 18px 0 8px; }
.subsection { font-size: 13px; margin: 8px 0 6px; color: var(--muted); }
.modal.wide { width: min(900px, 100%); }
.evidence-card { background: #fff; border: 1px solid var(--border); border-radius: 8px; padding: 12px; margin-bottom: 14px; }
.evidence-head { display: flex; align-items: center; gap: 12px; margin-bottom: 8px; flex-wrap: wrap; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; background: #e2e8f0; }
.badge.ok { background: #dcfce7; color: #166534; }
.badge.warn { background: #fef3c7; color: #92400e; }
.badge.danger { background: #fee2e2; color: #991b1b; }
</style>
