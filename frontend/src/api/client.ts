import axios from 'axios'
import { message } from '../utils/discrete'

const client = axios.create({
  baseURL: '/api',
  timeout: 120_000,
})

// Response interceptor: unwrap .data + global error toast
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const msg = err.response?.data?.detail || err.message
    message.error(msg, { duration: 5000, closable: true })
    return Promise.reject(new Error(msg))
  },
)

export default client
