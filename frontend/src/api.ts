import type { Job, Tracking, Status } from './model'
export type BoardData = { jobs:Job[]; scan:Record<string,unknown> }
async function request<T>(url:string,init?:RequestInit):Promise<T> {
  const response=await fetch(url,{...init,signal:AbortSignal.timeout(15000)})
  const body=await response.json()
  if(!response.ok) throw new Error(typeof body.error==='string'?body.error:body.error?.message||'Request failed')
  return body
}
export const readBoard=()=>request<BoardData>('/api/jobs')
export const saveTracking=(identity:string,status:Status,notes:string)=>request<Tracking>('/api/tracking',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identity,status,notes})})
