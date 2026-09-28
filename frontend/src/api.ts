import type { Job, Tracking, Status, Sort } from './model'
export type BoardData = { jobs:Job[]; total:number; counts:Partial<Record<Status,number>>; scan:Record<string,unknown> }
export type BoardQuery = { status:Status; q?:string; provider?:string; sort?:Sort; closed?:boolean; unverified?:boolean; offset?:number; limit?:number }
export type JobDetail = { description:string; assessment:string }
async function request<T>(url:string,init?:RequestInit):Promise<T> {
  const response=await fetch(url,{...init,signal:AbortSignal.timeout(15000)})
  const body=await response.json()
  if(!response.ok) throw new Error(typeof body.error==='string'?body.error:body.error?.message||'Request failed')
  return body
}
export const readBoard=(query:BoardQuery)=>{
  const params=new URLSearchParams({status:query.status,q:query.q??'',provider:query.provider??'all',sort:query.sort??'default',closed:query.closed?'1':'0',unverified:query.unverified?'1':'0',offset:String(query.offset??0),limit:String(query.limit??40)})
  return request<BoardData>(`/api/jobs?${params}`)
}
export const readJob=(identity:string)=>request<JobDetail>(`/api/jobs/detail?identity=${encodeURIComponent(identity)}`)
export const saveTracking=(identity:string,status:Status,notes:string)=>request<Tracking>('/api/tracking',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({identity,status,notes})})
