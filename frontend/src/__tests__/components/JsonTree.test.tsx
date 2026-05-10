import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { JsonTree } from '../../components/JsonTree'

describe('JsonTree', () => {
  it('renders primitive string', () => {
    render(<JsonTree data="hello" />)
    expect(screen.getByText('"hello"')).toBeInTheDocument()
  })

  it('renders primitive number', () => {
    render(<JsonTree data={42} />)
    expect(screen.getByText('42')).toBeInTheDocument()
  })

  it('renders object with expandable keys', () => {
    render(<JsonTree data={{ name: 'test', value: 123 }} />)
    expect(screen.getByText('name:')).toBeInTheDocument()
    expect(screen.getByText('value:')).toBeInTheDocument()
  })

  it('collapses and expands on click', () => {
    render(<JsonTree data={{ key: 'value' }} />)
    const button = screen.getByLabelText('折叠')
    fireEvent.click(button)
    expect(screen.getByLabelText('展开')).toBeInTheDocument()
    fireEvent.click(screen.getByLabelText('展开'))
    expect(screen.getByLabelText('折叠')).toBeInTheDocument()
  })

  it('renders array', () => {
    render(<JsonTree data={[1, 2, 3]} />)
    expect(screen.getByText('1')).toBeInTheDocument()
    expect(screen.getByText('2')).toBeInTheDocument()
    expect(screen.getByText('3')).toBeInTheDocument()
  })

  it('renders null', () => {
    render(<JsonTree data={null} />)
    expect(screen.getByText('null')).toBeInTheDocument()
  })
})
