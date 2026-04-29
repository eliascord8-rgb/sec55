import axios from "axios";

const BACKEND = process.env.REACT_APP_BACKEND_URL;
export const API = `${BACKEND}/api`;

export const api = axios.create({ baseURL: API });

export const adminApi = (token) =>
  axios.create({
    baseURL: API,
    headers: { "X-Admin-Token": token },
  });
