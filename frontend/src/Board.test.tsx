// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Board from './Board'
import { readBoard,saveTracking } from './api'
import type { Job } from './model'
vi.mock('./api',()=>({readBoard:vi.fn(),saveTracking:vi.fn()}))
const job:Job={identity:'ashby\t1',company:'Example',title:'Engineer one',location:'US',portal:'ashby',link:'https://example.com',description:'text',assessment:'',fit:null,priority:0,status:'new',notes:'',posted_at:'',checked_at:'',is_listed:true,applied_at:'',updated_at:''}
beforeEach(()=>{
  job.posted_at=new Date().toISOString()
  vi.mocked(readBoard).mockResolvedValue({jobs:[job],scan:{}} as Awaited<ReturnType<typeof readBoard>>)
  vi.mocked(saveTracking).mockReset()
  HTMLElement.prototype.scrollIntoView=vi.fn()
  HTMLElement.prototype.hasPointerCapture=()=>false
  HTMLElement.prototype.releasePointerCapture=vi.fn()
})
afterEach(()=>{cleanup();vi.clearAllMocks()})
async function edit() {
  render(<Board/>);fireEvent.click(await screen.findByRole('button',{name:'Engineer one'}))
  fireEvent.change(screen.getByLabelText('Notes'),{target:{value:'My notes'}})
}
it('failed saves retain notes and status membership',async()=>{
  vi.mocked(saveTracking).mockRejectedValue(new Error('offline'))
  await edit();fireEvent.click(screen.getByRole('button',{name:'Save tracking'}))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect((screen.getByLabelText('Notes') as HTMLTextAreaElement).value).toBe('My notes')
  expect(screen.getByRole('button',{name:'Engineer one',hidden:true})).toBeTruthy()
})
it('confirmed saves move out of Results and into Applied',async()=>{
  vi.mocked(saveTracking).mockResolvedValue({status:'applied',notes:'My notes',updated_at:'2026-09-26T12:00:00Z',applied_at:'2026-09-26T12:00:00Z'})
  await edit()
  const user=userEvent.setup()
  await user.click(screen.getByRole('combobox',{name:'Application status'}))
  await user.click(await screen.findByRole('option',{name:'Applied'}))
  fireEvent.click(screen.getByRole('button',{name:'Save tracking'}))
  await waitFor(()=>expect(screen.queryByRole('button',{name:'Engineer one'})).toBeNull())
  expect(saveTracking).toHaveBeenCalledWith('ashby\t1','applied','My notes')
  fireEvent.click(screen.getByRole('button',{name:'View tab'}))
  expect(await screen.findByRole('button',{name:'Engineer one'})).toBeTruthy()
})
it('refresh does not overwrite unsaved notes',async()=>{
  await edit()
  fireEvent.click(screen.getByRole('button',{name:'Refresh',hidden:true}))
  await waitFor(()=>expect(vi.mocked(readBoard)).toHaveBeenCalledTimes(2))
  expect((screen.getByLabelText('Notes') as HTMLTextAreaElement).value).toBe('My notes')
})
it('shows a direct application link without opening details',async()=>{
  render(<Board/>)
  const link=await screen.findByRole('link',{name:'Apply to Engineer one at Example'})
  expect(link.getAttribute('href')).toBe('https://example.com')
  expect(link.getAttribute('target')).toBe('_blank')
  expect(screen.queryByLabelText('Notes')).toBeNull()
})
it('card status saves existing notes and moves only after confirmation',async()=>{
  let finish:(value:Awaited<ReturnType<typeof saveTracking>>)=>void=()=>{}
  vi.mocked(readBoard).mockResolvedValue({jobs:[{...job,notes:'Existing notes'}],scan:{}})
  vi.mocked(saveTracking).mockImplementation(()=>new Promise(resolve=>{finish=resolve}))
  render(<Board/>);const user=userEvent.setup()
  await user.click(await screen.findByRole('combobox',{name:'Status for Engineer one at Example'}))
  await user.click(await screen.findByRole('option',{name:'Applied'}))
  expect(saveTracking).toHaveBeenCalledWith(job.identity,'applied','Existing notes')
  expect(screen.getByRole('button',{name:'Engineer one'})).toBeTruthy()
  finish({status:'applied',notes:'Existing notes',updated_at:'now',applied_at:'now'})
  await waitFor(()=>expect(screen.queryByRole('button',{name:'Engineer one'})).toBeNull())
  fireEvent.click(screen.getByRole('button',{name:'View tab'}))
  expect(await screen.findByRole('button',{name:'Engineer one'})).toBeTruthy()
})
it('failed card status saves leave the job in Results',async()=>{
  vi.mocked(saveTracking).mockRejectedValue(new Error('offline'))
  render(<Board/>);const user=userEvent.setup()
  await user.click(await screen.findByRole('combobox',{name:'Status for Engineer one at Example'}))
  await user.click(await screen.findByRole('option',{name:'Applied'}))
  expect(await screen.findByRole('alert')).toBeTruthy()
  expect(screen.getByRole('button',{name:'Engineer one'})).toBeTruthy()
  expect(screen.getByRole('combobox',{name:'Status for Engineer one at Example'}).textContent).toContain('New')
})
