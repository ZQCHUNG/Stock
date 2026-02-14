import axios from 'axios'

const client = axios.create({
  baseURL: '/api',
  timeout: 120_000,
})

// Response interceptor: unwrap .data
client.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const msg = err.response?.data?.detail || err.message
    return Promise.reject(new Error(msg))
  },
)

export default client
