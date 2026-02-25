import axios from 'axios'
import { message } from '../utils/discrete'

const client = axios.create({
  baseURL: '/api',
  timeout: 20_000, // Sprint 15: 20s default (was 120s — CTO: "120s = system dead")
})

// Response interceptor: unwrap .data + global error toast
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const status = err.response?.status
    const serverMsg = err.response?.data?.message || err.response?.data?.detail

    // Sprint 15 P0-B: User-friendly timeout message
    if (status === 504 || err.code === 'ECONNABORTED') {
      const hint = serverMsg || '伺服器回應超時，此股票可能尚未快取'
      message.warning(hint, { duration: 5000, closable: true })
      return Promise.reject(new Error(hint))
    }

    const msg = serverMsg || err.message
    message.error(msg, { duration: 5000, closable: true })
    return Promise.reject(new Error(msg))
  },
)

export default client
