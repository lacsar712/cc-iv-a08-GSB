<template>
  <main>
    <h1>光伏组串IV扫描台</h1>
    <nav v-if="session" class="topbar">
      <button class="navbtn" :class="{ on: view === 'scans' }" @click="switchView('scans')">扫描台</button>
      <button class="navbtn" :class="{ on: view === 'golden' }" @click="switchView('golden')">黄金窗</button>
    </nav>
    <div v-if="!session">
      <p class="sub">扫描员提交开路电压、短路电流与填充因子；通知通道叫醒工人出结论。登录框已预填可写账号 scanner / scan123456。</p>
      <section>
        <label>用户名</label><input v-model="loginUser" autocomplete="off" />
        <label>密码</label><input type="password" v-model="loginPass" autocomplete="off" />
        <button :disabled="loading" @click="login">登录</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
    </div>
    <div v-else-if="view === 'scans'">
      <p class="sub">已登录：{{ session.username }}（{{ isWriter ? "可提交" : "只读" }}）</p>
      <section>
        <button class="secondary" @click="logout">退出</button>
        <button class="secondary" @click="refresh">刷新列表</button>
      </section>
      <section v-if="isWriter">
        <label>组串编号</label><input v-model="stringCode" placeholder="例如 阵列C-串05" />
        <label>开路电压 V</label><input type="number" step="0.1" v-model="voc" />
        <label>短路电流 A</label><input type="number" step="0.1" v-model="isc" />
        <label>填充因子</label><input type="number" step="0.01" v-model="ff" />
        <button :disabled="loading" @click="submit">提交扫描</button>
        <p v-if="error" class="err">{{ error }}</p>
      </section>
      <section>
        <table>
          <thead>
            <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>状态</th><th>结论</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in logs" :key="row.id">
              <td>{{ row.id }}</td>
              <td>{{ row.string_code }}</td>
              <td>{{ row.voc_v }}</td>
              <td>{{ row.isc_a }}</td>
              <td>{{ row.fill_factor }}</td>
              <td><span class="tag" :class="row.status === 'pending' ? 'pending' : 'ok'">{{ row.status === 'pending' ? '待处理' : '已完成' }}</span></td>
              <td><span v-if="row.verdict" class="tag" :class="row.verdict === '合格' ? 'ok' : 'bad'">{{ row.verdict }}</span><span v-else>—</span></td>
            </tr>
          </tbody>
        </table>
      </section>
    </div>
    <div v-else>
      <p class="sub">黄金窗：逆变器刚启动后的十分钟。已登录：{{ session.username }}（{{ isWriter ? "可封存" : "只读" }}）</p>
      <section>
        <h2>窗名</h2>
        <template v-if="isWriter">
          <label>册名</label>
          <input v-model="bookName" placeholder="例如 启动黄金窗·第一册" />
          <button :disabled="loading || !bookName.trim()" @click="seal">封存</button>
        </template>
        <p v-else class="note">观察员能翻旧曲线，不能按封存。</p>
        <p v-if="goldenError" class="err">{{ goldenError }}</p>
      </section>
      <section>
        <h2>在途轨迹</h2>
        <p v-if="!inflight.length" class="empty">还没有曲线</p>
        <table v-else>
          <thead>
            <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>提交时间</th></tr>
          </thead>
          <tbody>
            <tr v-for="row in inflight" :key="row.id">
              <td>{{ row.id }}</td>
              <td>{{ row.string_code }}</td>
              <td>{{ row.voc_v }}</td>
              <td>{{ row.isc_a }}</td>
              <td>{{ row.fill_factor }}</td>
              <td>{{ fmtTime(row.created_at) }}</td>
            </tr>
          </tbody>
        </table>
      </section>
      <section>
        <h2>查阅旧册</h2>
        <p v-if="!books.length" class="empty">还没有曲线</p>
        <div v-for="book in books" :key="book.id" class="book">
          <h3>{{ book.name }}</h3>
          <p class="meta">封存人 {{ book.created_by }} · {{ fmtTime(book.created_at) }} · 共 {{ book.points.length }} 串</p>
          <table>
            <thead>
              <tr><th>#</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th></tr>
            </thead>
            <tbody>
              <tr v-for="p in book.points" :key="p.id">
                <td>{{ p.seq + 1 }}</td>
                <td>{{ p.string_code }}</td>
                <td>{{ p.voc_v }}</td>
                <td>{{ p.isc_a }}</td>
                <td>{{ p.fill_factor }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>
    </div>
  </main>
</template>
<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";
const session = ref(null);
const logs = ref([]);
const books = ref([]);
const view = ref("scans");
const loginUser = ref("scanner");
const loginPass = ref("scan123456");
const stringCode = ref("");
const voc = ref("");
const isc = ref("");
const ff = ref("");
const bookName = ref("");
const error = ref("");
const goldenError = ref("");
const loading = ref(false);
let timer;
const isWriter = computed(() => session.value?.role === "writer");
const inflight = computed(() => logs.value.filter((r) => r.status === "pending"));
function headers() {
  return session.value ? { Authorization: "Bearer " + session.value.token } : {};
}
function fmtTime(s) {
  if (!s) return "—";
  const d = new Date(s);
  return isNaN(d) ? s : d.toLocaleString();
}
async function refresh() {
  if (!session.value) return;
  const res = await fetch("/api/logs", { headers: headers() });
  if (res.status === 401) { logout(); return; }
  if (res.ok) logs.value = await res.json();
  const bres = await fetch("/api/golden-window/books", { headers: headers() });
  if (bres.ok) books.value = await bres.json();
}
function switchView(v) {
  view.value = v;
  goldenError.value = "";
  refresh();
}
async function login() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: loginUser.value, password: loginPass.value }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "登录失败"; return; }
    session.value = { token: data.access_token, username: data.username, role: data.role };
    localStorage.setItem("pv_session", JSON.stringify(session.value));
    await refresh();
    timer = setInterval(refresh, 2000);
  } catch { error.value = "无法连接接口"; }
  finally { loading.value = false; }
}
function logout() {
  if (timer) clearInterval(timer);
  session.value = null;
  logs.value = [];
  books.value = [];
  view.value = "scans";
  localStorage.removeItem("pv_session");
}
async function submit() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/logs", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({
        string_code: stringCode.value,
        voc_v: Number(voc.value),
        isc_a: Number(isc.value),
        fill_factor: Number(ff.value),
      }),
    });
    const data = await res.json();
    if (!res.ok) { error.value = data.detail || "提交失败"; return; }
    stringCode.value = voc.value = isc.value = ff.value = "";
    await refresh();
  } catch { error.value = "提交时网络异常"; }
  finally { loading.value = false; }
}
async function seal() {
  goldenError.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/golden-window/seal", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ name: bookName.value }),
    });
    const data = await res.json();
    if (!res.ok) { goldenError.value = data.detail || "封存失败"; return; }
    bookName.value = "";
    await refresh();
  } catch { goldenError.value = "封存时网络异常"; }
  finally { loading.value = false; }
}
onMounted(() => {
  const raw = localStorage.getItem("pv_session");
  if (raw) {
    try {
      session.value = JSON.parse(raw);
      refresh();
      timer = setInterval(refresh, 2000);
    } catch { localStorage.removeItem("pv_session"); }
  }
});
onUnmounted(() => { if (timer) clearInterval(timer); });
</script>
<style>
body { margin: 0; font-family: "Segoe UI", system-ui, sans-serif; background: #052e16; color: #ecfdf5; }
main { max-width: 980px; margin: 0 auto; padding: 1.5rem; }
h1 { color: #86efac; margin: 0 0 0.25rem; }
h2 { color: #86efac; font-size: 1.05rem; margin: 0 0 0.75rem; }
h3 { color: #bbf7d0; font-size: 0.95rem; margin: 0 0 0.25rem; }
.sub { color: #a7f3d0; margin-bottom: 1.25rem; }
section { background: #14532d; border: 1px solid #166534; border-radius: 8px; padding: 1rem 1.25rem; margin-bottom: 1rem; }
label { display: block; font-size: 0.85rem; margin-bottom: 0.25rem; }
input { width: 100%; box-sizing: border-box; padding: 0.5rem 0.65rem; border-radius: 6px; border: 1px solid #4ade80; background: #022c22; color: #ecfdf5; margin-bottom: 0.75rem; }
button { cursor: pointer; padding: 0.5rem 1rem; border: none; border-radius: 6px; background: #16a34a; color: #fff; font-weight: 600; margin-right: 0.4rem; }
button:disabled { opacity: 0.5; cursor: not-allowed; }
button.secondary { background: #365314; }
.topbar { display: flex; gap: 0.4rem; background: #022c22; border: 1px solid #166534; border-radius: 8px; padding: 0.5rem 0.75rem; margin: 0.75rem 0 1rem; }
.navbtn { background: transparent; color: #a7f3d0; border: 1px solid #166534; margin-right: 0; }
.navbtn.on { background: #16a34a; color: #fff; }
.err { color: #fecaca; }
.note { color: #a7f3d0; font-size: 0.85rem; }
.empty { color: #6ee7b7; font-style: italic; }
.book { border-top: 1px solid #166534; padding-top: 0.75rem; margin-top: 0.75rem; }
.meta { color: #a7f3d0; font-size: 0.8rem; margin: 0 0 0.5rem; }
table { width: 100%; border-collapse: collapse; font-size: 0.9rem; }
th, td { text-align: left; padding: 0.45rem; border-bottom: 1px solid #166534; }
.tag { padding: 0.1rem 0.4rem; border-radius: 4px; font-size: 0.8rem; }
.ok { background: #14532d; color: #bbf7d0; }
.bad { background: #7f1d1d; color: #fecaca; }
.pending { background: #854d0e; color: #fde68a; }
</style>
