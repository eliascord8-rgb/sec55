import axios from "axios";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND}/api`;

export const api = axios.create({ baseURL: API });

export const adminApi = (token) => {
  const instance = axios.create({
    baseURL: API,
    headers: { "X-Admin-Token": token },
  });

  instance.interceptors.response.use(
    (response) => response,
    (error) => {
      const status = error.response?.status;
      const detail = String(error.response?.data?.detail || "").toLowerCase();
      if (status === 401 || (status === 403 && detail.includes("unauthorized"))) {
        // Do not immediately drop the admin session on a single auth challenge.
        // Some panels hit endpoints that can briefly reject during normal state changes.
        if (typeof window !== "undefined") {
          window.dispatchEvent(new Event("bs-admin-auth-challenge"));
        }
      }
      return Promise.reject(error);
    }
  );

  return instance;
};
