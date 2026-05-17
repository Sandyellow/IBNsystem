import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_BASE_URL || `http://${window.location.hostname}:8000/api`

const api = axios.create({
  baseURL: API_BASE,
  timeout: 15000,
})

export default api
