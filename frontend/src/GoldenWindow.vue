<template>
  <div>
    <section>
      <h2 class="region">窗名区</h2>
      <p class="sub">
        逆变器启动后十分钟为黄金窗（{{ fmt(state.window_opened_at) }} 起，
        至 {{ fmt(state.window_closes_at) }} 止）。
        封存有写权限的扫描员可按，观察员只能翻旧曲线。
      </p>
      <template v-if="state">
        <p v-if="state.in_window" class="okline">
          黄金窗开启中，剩余 {{ remainLabel }}
        </p>
        <p v-else class="err">黄金窗已关闭，不能再封存。</p>
      </template>
      <template v-if="isWriter">
        <label>窗名</label>
        <input v-model="windowName" placeholder="例如 启动首窗-20261006" autocomplete="off" />
        <button :disabled="loading || !canSeal" @click="seal">封存</button>
      </template>
      <p v-else class="sub">当前为观察员账号：可翻阅旧曲线，不能按封存。</p>
      <p v-if="error" class="err">{{ error }}</p>
    </section>

    <section>
      <h2 class="region">轨迹区 · 此刻在途（{{ state ? state.in_flight.length : 0 }} 串）</h2>
      <p v-if="!state || state.in_flight.length === 0" class="sub">此刻没有在途读数。</p>
      <table v-else>
        <thead>
          <tr><th>编号</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>提交人</th><th>读数时间</th></tr>
        </thead>
        <tbody>
          <tr v-for="row in state.in_flight" :key="row.id">
            <td>{{ row.id }}</td>
            <td>{{ row.string_code }}</td>
            <td>{{ row.voc_v }}</td>
            <td>{{ row.isc_a }}</td>
            <td>{{ row.fill_factor }}</td>
            <td>{{ row.created_by }}</td>
            <td>{{ fmt(row.created_at) }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section>
      <h2 class="region">查阅区 · 已封曲线册（{{ state ? state.albums.length : 0 }} 本）</h2>
      <p v-if="!state || state.albums.length === 0" class="sub">还没有曲线。</p>
      <ul v-else class="albums">
        <li v-for="album in state.albums" :key="album.id">
          <button class="secondary link" @click="toggle(album.id)">
            {{ openId === album.id ? "▾" : "▸" }} 第{{ album.id }}册 · {{ album.window_name }}
          </button>
          <span class="meta">
            {{ album.point_count }} 串 · 封存人 {{ album.sealed_by }} · {{ fmt(album.sealed_at) }}
          </span>
          <div v-if="openId === album.id && detail" class="detail">
            <table>
              <thead>
                <tr><th>点序</th><th>源单</th><th>组串</th><th>Voc</th><th>Isc</th><th>FF</th><th>当时读数时间</th></tr>
              </thead>
              <tbody>
                <tr v-for="(p, i) in detail.points" :key="p.id">
                  <td>{{ i + 1 }}</td>
                  <td>{{ p.scan_id }}</td>
                  <td>{{ p.string_code }}</td>
                  <td>{{ p.voc_v }}</td>
                  <td>{{ p.isc_a }}</td>
                  <td>{{ p.fill_factor }}</td>
                  <td>{{ fmt(p.reading_created_at) }}</td>
                </tr>
              </tbody>
            </table>
          </div>
        </li>
      </ul>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from "vue";

const props = defineProps({ session: { type: Object, required: true } });

const state = ref(null);
const windowName = ref("");
const error = ref("");
const loading = ref(false);
const openId = ref(null);
const detail = ref(null);
let timer;
let ticker;
const nowTick = ref(Date.now());

const isWriter = computed(() => props.session?.role === "writer");

// 以服务器时间为基准走秒，避免本机时钟偏差。
const remainMs = computed(() => {
  if (!state.value) return 0;
  void nowTick.value;
  const skew = Date.parse(state.value.server_now) - Date.now();
  return Date.parse(state.value.window_closes_at) - (Date.now() + skew);
});
const remainLabel = computed(() => {
  const s = Math.max(0, Math.round(remainMs.value / 1000));
  const m = Math.floor(s / 60);
  return `${m} 分 ${s % 60} 秒`;
});
const canSeal = computed(
  () => state.value?.in_window && state.value.in_flight.length > 0 && windowName.value.trim()
);

function headers() {
  return { Authorization: "Bearer " + props.session.token };
}
function fmt(v) {
  return v ? new Date(v).toLocaleString("zh-CN", { hour12: false }) : "—";
}

async function refresh() {
  const res = await fetch("/api/golden/state", { headers: headers() });
  if (res.ok) state.value = await res.json();
}

async function toggle(id) {
  if (openId.value === id) {
    openId.value = null;
    detail.value = null;
    return;
  }
  openId.value = id;
  detail.value = null;
  const res = await fetch(`/api/golden/albums/${id}`, { headers: headers() });
  if (res.ok) detail.value = await res.json();
}

async function seal() {
  error.value = "";
  loading.value = true;
  try {
    const res = await fetch("/api/golden/seal", {
      method: "POST",
      headers: { "Content-Type": "application/json", ...headers() },
      body: JSON.stringify({ window_name: windowName.value.trim() }),
    });
    const data = await res.json();
    if (!res.ok) {
      error.value = data.detail || "封存失败";
      return;
    }
    windowName.value = "";
    await refresh();
    // 封存完直接摊开新册，核对点列。
    openId.value = data.id;
    detail.value = data;
  } catch {
    error.value = "封存时网络异常";
  } finally {
    loading.value = false;
  }
}

onMounted(() => {
  refresh();
  timer = setInterval(refresh, 2000);
  ticker = setInterval(() => { nowTick.value = Date.now(); }, 1000);
});
onUnmounted(() => {
  clearInterval(timer);
  clearInterval(ticker);
});
</script>

<style scoped>
.region { color: #86efac; margin: 0 0 0.5rem; font-size: 1.05rem; }
.okline { color: #bbf7d0; font-weight: 600; }
input { max-width: 320px; }
.albums { list-style: none; padding: 0; margin: 0; }
.albums li { padding: 0.5rem 0; border-bottom: 1px solid #166534; }
.link { text-align: left; }
.meta { color: #a7f3d0; font-size: 0.85rem; margin-left: 0.5rem; }
.detail { margin-top: 0.6rem; }
</style>
