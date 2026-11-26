import { createRouter, createWebHistory } from 'vue-router'

import Overview from '@/views/Overview.vue'
import ReportDistView from '@/views/ReportDistView.vue'
import ConclusionReviewView from '@/views/ConclusionReviewView.vue'
import WorkbenchView from '@/views/WorkbenchView.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'overview', component: Overview },
    // 专用工作台必须放在动态模块路由之前，避免被 /:moduleKey 抢先匹配
    { path: '/report_dist', name: 'report-dist-workflow', component: ReportDistView },
    { path: '/conclusion_review', name: 'conclusion-review-workflow', component: ConclusionReviewView },
    { path: '/:moduleKey', name: 'module', component: WorkbenchView, props: true },
  ],
})

export default router
