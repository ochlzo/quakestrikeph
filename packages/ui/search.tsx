"use client"

import type * as React from "react"
import { Group as GroupPrimitive, Input as InputPrimitive } from "react-aria-components"
import { SearchIcon } from "lucide-react"
import { Spinner } from "./spinner"
import "./search.css"

type SearchProps = Omit<React.ComponentProps<typeof GroupPrimitive>, "children"> & {
  children?: React.ReactNode
  isLoading?: boolean
}

/**
 * Bulletin's search appearance: 52px height, 14px side padding, an 8px icon gap,
 * and a 20px search icon. SearchInput owns the accessible name and input props.
 *
 * <Search><SearchInput aria-label="Search by Province" /></Search>
 *
 * Inside a Combobox, SearchInput inherits its input context. Place an optional
 * ComboboxTrigger after SearchInput. isLoading replaces the leading icon with
 * the shared Spinner without moving the input. The caller owns request state;
 * Search adds no filtering, labels, or dropdowns of its own.
 */
function Search({ children, isLoading = false, ...props }: SearchProps) {
  return (
    <GroupPrimitive data-slot="search" aria-busy={isLoading || undefined} {...props}>
      {isLoading ? <Spinner aria-hidden="true" /> : <SearchIcon size={20} aria-hidden="true" />}
      {children}
    </GroupPrimitive>
  )
}

function SearchInput(props: React.ComponentProps<typeof InputPrimitive>) {
  return <InputPrimitive data-slot="search-input" {...props} />
}

export { Search, SearchInput, type SearchProps }
