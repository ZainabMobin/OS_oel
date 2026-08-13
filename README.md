
| CS330: Operating Systems | Lab 11: File Management System | Lab 12: Open-Ended Lab | Design Document |
-|-|-|-

<br>

# FILE SYSTEM DESIGN

## Quick Run 

Run `shell.py` to start the CLI interface. Use the provided sample.dat as a starting point, if the file is not present in the directory then the program creates and initializes it in the following format:

```JSON
header = {"files": {}, "dead_space": []} <<<DATA>>> [raw bytes]
```

You can create your own filesystem.dat from scratch, but it must match the initial format.

## 1. Overview

The system simulates a virtual file system stored entirely within a single data file (filesystem.dat). The implementation uses a hybrid architecture that balances simplicity with realistic OS-level behavior.

This document describes the design decisions made for the file management system in Labs 11 and 12.


## 2. Project Structure and File Roles
| File	| Responsibility |
-|-
| filesystem.dat	| The single data file — JSON header + separator + raw bytes |
| fs_core.py |	FileSystem class: load/save .dat, create, delete, mkdir, chdir, move, compaction, memory map
| file_object.py |	FileObject class: open, read, write, write_at, move_within_file, truncate, close
| shell.py	| CLI loop: parses user commands and calls fs_core / file_object methods
| sample.dat |	Pre-populated example filesystem for demonstration


## 3. Structure of filesystem.dat

The core design uses a Hybrid approach that divides filesystem.dat into two logical regions:

|Region|	What It Contains|	Technology Used|
|-|-|-|
|JSON Header|	Flattened directory tree, file metadata, byte offsets, segment maps|	Python dict serialized as JSON
|Separator|	A fixed delimiter separating the two regions | String `<<<DATA>>>`| 
|Raw Data Section|	Actual file contents at specific byte offsets	|Binary/text bytes written directly

This means directory management uses Python's natural dict/JSON capabilities while actual file content sits at real byte offsets, giving a meaningful memory map without the full complexity of a block-based file system.

### 3.1 Visual Layout
---

**filesystem.dat**

      ┌─────────────────────────────────────────────┐
      │  JSON HEADER                                │
      │  {                                          │
      │    "directories": [ <list of items > ],     │
      │    "files": {     < file list >     },      │
      │    "dead_space": [ < region info> ]         │
      │  }                                          │
      ├─────────────────────────────────────────────┤
      │  <<<DATA>>>                                 │  ← separator
      ├─────────────────────────────────────────────┤
      │  [bytes of notes.txt seg 1: offset 0  ]     │
      │  [bytes of essay.txt:       offset 200]     │
      │  [bytes of readme.txt:      offset 400]     │
      │  [bytes of notes.txt seg 2: offset 600]     │
      └─────────────────────────────────────────────┘

### 3.2 JSON Header Schema

```JSON
{{
    "directories": [
		{"id": 0, "name": "/", "parent": null, "type": "dir"},
		{"id": 12884470763231440000, "name": "newFolder", "parent": 0, "type": "dir" }
		...
    ],

    "files": {
		"test.txt": 	{	"size": 11, 
							"segments": [
								{ "offset": 0, "length": 11 },
								{ "offset": 25, "length": 9 }
							]
						},

		"sample.txt":	{ ... },
		...
    },

    "dead_space": [
        { "offset": 168, "size": 209 },
        ...
    ]
}}
```

### Schema Details

- **`directories` dict:**
	 
	Each file/folder item in `directories` dictionary in the JSON tree contains objects with the following attributes:

	| Field |	Type |	Description |
	|-------|------|--------------|
	| id	| long int | ID of file/folder |
	| name |	string |	name of file/folder (without path) |
	| parent	| long int | Points to parent dir ID |
	| type |	string |	`file` or `dir` |

	IDs are generated via sha256 using the full file/folder path from the root `/`, ensuring unique ID for items (file/folder) with the same name. Though this needs the enforcement that two items with the same name do not exist in same directory simultaneously, notably resembling OS behaviour.

	```JSON
			{"id": 0, "name": "/", "parent": null, "type": "dir"},
			{"id": 12884470763231440000, "name": "ewFolder", "parent": 0, "type": "dir" }
	```

- **`files` object:**

	Each file item in `files` object tree contains an object with the following attributes, leading from the file name:

	| Field |	Type |	Description |
	|-------|------|--------------|
	| size | int |	Total bytes of file content across all segments |
	| segments	| list |	Ordered list of {offset, length} dicts pointing into raw data section |

	```JSON
		"sample.txt":	{ 
			"size": 5,
			"segments": [ 
				{ "offset": 35, "length": 9 },
				{ "offset": 57, "length": 4 },
				{ "offset": 83, "length": 5 }
			]			
		}
	```

- **`dead_space` dict:**

	The `dead_space` dictionary cotains entries wit teh following attributes: 
	| Field |	Type |	Description |
	|-------|------|--------------|
	| offset | int | Starting byte position of the dead space |
	| size | int | size of dead space in bytes |


	```JSON
			{ "offset": 168, "size": 209 }
	```


## 4. Segmentation Design
### 4.1 Why Segments?
---
Files do not always fit in one contiguous region. Rather than reshuffling all bytes every time a file grows (which is O(n) overhead on every write), files are allowed to have multiple segments. Each segment is an independent contiguous chunk in the raw data section.

When a file overflows its current last segment, a new segment is appended at the end of the raw data section. No existing bytes are moved.

### 4.2 Segment Growth Strategy
---
Situation	Action
Write fits in last segment	Write in place, update length
Write overflows last segment	Allocate new segment at end of raw section, append overflow there
Truncate reduces size	Remove trailing segments, trim last remaining segment

## 5. Dead Space and Compaction
### 5.1 How Dead Space Arises
---
Two operations produce dead (orphaned) bytes in the raw data section:
- Delete — the JSON entry is removed but the raw bytes at the old offsets remain untouched.
- Move within file — the source bytes are zeroed/abandoned after being copied to the destination.

During a session, dead regions accumulate between live segments. This is intentional and mirrors real file system behavior (deleted files linger on disk until overwritten).
### 5.2 Compaction on Startup
---
Rather than managing a free list at runtime (which adds significant complexity), compaction is deferred to program startup:
- Step 1 — Load all live segments from the JSON tree into a flat list.
- Step 2 — Rewrite the raw data section with only live segments, packed contiguously.
- Step 3 — Update all segment offsets in the JSON to match the new positions.
- Step 4 — Save the cleaned filesystem.dat.

This means fragmentation is visible mid-session on the memory map (which is educational) but is always cleaned up at the start of each new session.

## 6. Memory Map Generation
### 6.1 The Problem with JSON Traversal Order
---
The JSON tree is organized by directory structure, not by byte offset. Traversing it directly does not guarantee offset-ordered output. For example, a file deep in a subdirectory might have a lower byte offset than a file in root.
### 6.2 Algorithm
---
- Traverse the entire JSON tree and collect every segment from every file into a flat list, tagged with the file's full path.
- Sort the flat list by offset.
- Walk through the sorted list, comparing each entry's expected_next_offset against the actual next entry's offset.
- If a gap exists, insert a DEAD region of that length between them.
- After the last live segment, show FREE space to end of file.

Gap detection formula:
expected_next = current.offset + current.length
if expected_next < next.offset:
    dead_length = next.offset - expected_next
    → insert DEAD region at expected_next

### 6.3 Sample Memory Map Output
---

| Offset |	Length |	Status |	File |
|-|-|-|-|
| 0 |	200 |	LIVE |	/root/notes.txt  (seg 1) |
| 200 |	200 |	DEAD |	(deleted: essay.txt) |
| 400 |	30 |	LIVE |	/root/docs/readme.txt |
| 430 |	170 |	DEAD |	(move_within_file residue) |
| 600 |	15 |	LIVE |	/root/notes.txt  (seg 2) |
| 615 |	— |	FREE |	(never written) |
 
## 7. Function Behaviour Summary

| Function command | Purpose | JSON Impact |	Raw Data Impact |
|-|-|-|-|
| `create <filename>`  | Create an empty file in current dir |	Add entry, segments=[], size=0 |	None until first write |
| `delete <filename> `|	Delete a file | Remove entry from tree |	Raw bytes orphaned (dead space) |
| `mkdir <dirName>`	| Create directory in current dir  | Add dir entry with empty children |	None |
| `chdir <dirName>	`| Change Directory | Update cwd pointer in JSON |	None |
| `chdir ..`	| Move up to parent Directory | Update cwd pointer in JSON |	None |
| `move <src> <dst>`	| Move file from source to destination | Reassign entry under new dir |	None — offsets unchanged |
| `open <mode>  <filename>` | Open file in a mode	| None |	None — returns FileObject |
| `open read <filename> `| Read full file | None |	Read all segments in order, concatenate
| `open read <filename> [start] [size]` | Read file from a specific part | None |	Walk segments to start offset, read size bytes
| `open write <filename> 'text'` | Write to a file | Update size, add segment if overflow |	Write at end of last segment or new segment |
|`   open write <filename> <pos> 'text'`	| Wrtie at a specific part of file | Update size if grown |	Overwrite at byte position; extend if past end |
|` open move_within <filename> <start> <size> <target>` | Move text within file| None	| Read chunk, zero source, write_at destination |
|` open truncate <filename> <max_size> `| Truncate file from the end| Remove trailing segments, update size |	Trailing segment bytes become dead space |
| `close <filename> `| close an open file | None | None - auto-close file after file operation takes place
| `mmap` | Show Memory Map	| Traverse tree → collect all segments |	Sort by offset, infer dead regions by gap detection |
|` man` / `help` | Show function manual |None | None
| `ls` | List files and Directories from current directory| None | None
| `q` | Quit loop|None|None


## 8. Key Design Decisions & Rationale
Decision |	Alternative Considered	| Why This Choice
-|-|-
Hybrid JSON + raw bytes	| Pure JSON (content in header) |	Pure JSON felt like cheating for an OS course — no real byte simulation
Segmented files (multi-segment) |	Reserved padding per file |	Padding causes empty holes requiring a free list; segments avoid both reshuffling and free list complexity
Delete = JSON removal only |	Immediate byte reclamation | Mirrors real OS behavior; runtime free list adds too much overhead
Compaction on startup	| Runtime compaction / free list |	One clean sweep per session is sufficient; free list merge logic is a rabbit hole
Sort + gap detection for memory map	| Rely on JSON traversal order | JSON is organized by directory, not offset; sorting guarantees correct physical order
write_at = overwrite (not insert) |	Insert and shift	| Lab spec says may overwrite; insert would require shifting all subsequent bytes across segments


## 9. Detailed Thought process for Advanced Space Management: Dead Segment Reuse and Logical Order Preservation
The baseline design defers all dead space reclamation to a single startup compaction pass. This can cause unnecessary fragmentation during long sessions and incurs a fixed I/O cost at every program launch. The following optional enhancements reduce both runtime fragmentation and the frequency of full compaction events.

Field  |	Description
-|-
`offset` |	Starting byte position of the dead block
`length` |	Size of the dead block in bytes

### 9.1 Dead Segment Table (Free Space Tracking)
---
Instead of ignoring dead space until the next startup, maintain an in-memory dead segment table that records every orphaned byte range in the raw data section. 

It is persisted in filesystem.dat within the header. The table is populated whenever a file is deleted, truncated, or when a move_within_file operation abandons its source bytes.

### 9.2 Segment Placement Policy: Favour Logical Physical Coherence
---
When a new segment must be allocated (e.g., due to an overflow write or file creation with initial data), the allocator inspects the dead segment table and applies the following best fit with logical order bias heuristic: 
- Identify all dead segments large enough to hold the requested data.
- Filter candidates that lie at a physical offset before the offset of the file’s next logical segment (or after the previous logical segment).
- Choose the smallest suitable dead segment among those that preserve the logical order.
- If no suitable dead segment exists, append the new segment to the free space at the end of the raw data section.

This policy ensures that, whenever possible, the physical layout of segments mirrors the logical order of the file. The benefit is a reduction in the number of disk seeks during sequential reads, as fragments are more likely to be stored consecutively.

### 9.3 Threshold Based Compaction (On Demand Cleanup)
---
Dead segment reuse cannot eliminate all fragmentation. Two scenarios still degrade read performance:
- Scattered small dead segments that are too tiny to be reused (internal fragmentation).
- End of file modifications that do not trigger new allocations, causing the dead segment table to grow while the physical layout stagnates.
To address this, implement a condition based cleanup analogous to background defragmentation in modern file systems:
- Threshold Trigger: After every N allocation operations (or when the total dead space exceeds some threshold, say 20% of the raw data section size), initiate a background compaction.

- Compaction Process: Perform streaming copy in Section ## 5.2, but only on the live segments.
  - Update all JSON segment offsets to the new contiguous positions.
  - Clear the dead segment table (all dead space is now converted to a single contiguous free region at the end of the file).

This lazy cleanup avoids the I/O penalty of compacting at every startup while still preventing the filesystem from degrading into a severely fragmented state over long running sessions.

## 10. Detailed Thought process for Metadata Storage Scalability: JSON Overhead and Reserved Regions

### 10.1 The Problem: Unbounded Header Growth
---
The hybrid design stores the entire directory tree and file metadata as a single JSON object at the start of filesystem.dat. While simple and debuggable, this approach has two scalability limitations:
- **Verbose Encoding:** JSON stores field names as plain text (e.g., "segments" repeated thousands of times). For a filesystem containing 10,000 files, the metadata header alone could exceed several megabytes, even though the actual information (names, offsets, sizes) is only a few hundred kilobytes.
- **Header Data Boundary Shifting:** Every time a file is created, deleted, or renamed, the JSON header changes size. Because the raw data section immediately follows the header, any header expansion forces the entire raw data section to be rewritten—the very problem segmentation was meant to avoid.

### 10.2 Real World Precedent: Fixed Metadata Regions
---
Production file systems do not intermingle variable length metadata with file data in a single contiguous stream. Instead, they allocate a fixed, reserved region at the beginning (or at known intervals) of the storage device for metadata structures.

These reserved regions ensure that metadata can grow and shrink within its own boundary without ever colliding with file data.

### 10.3 Proposed Mitigations for the Lab Filesystem
---

**A) Reserve a Fixed Header Space (Simplest)**

**Implementation:** Define a maximum header size (e.g., 1 MB or 10 MB) during filesystem creation. The first N bytes of filesystem.dat are permanently reserved for the JSON header. The raw data section begins at offset `HEADER_RESERVED_SIZE`.

**Handling Overflow:** If the JSON header exceeds the reserved space, the system returns an error `Filesystem metadata full; delete some files or increase reserved space.`

**Pros**
- Zero shifting of data section on header updates.
- Trivial to implement.
- Preserves JSON readability for debugging.

**Cons**
- Arbitrary limit on number of files.
- Wasted space if the reservation is too large.

**B) Binary Serialization of Metadata (Space Efficient)**

**Implementation:** Replace the JSON text header with a custom binary format using Python’s struct module or a library like pickle (with caution) or msgpack. Each metadata record becomes a fixed size or length prefixed binary entry.

**Space Savings:** A JSON entry like `{"name":"notes.txt","size":1024,"segments":[...]}`  might occupy 80 bytes; a binary equivalent using fixed length name fields and packed integers can be under 30 bytes.

**Pros**

- Drastically reduces metadata size and growth.
- Eliminates field name redundancy.
- Still allows for a reserved header region but with far less wasted space.

**Cons**
- Loss of human readability (debugging requires a hex dump or a separate tool).
- Slightly more complex parsing logic.

**C) Relocatable Metadata with Overflow Area (Most Realistic but Complex)**

**Implementation:** The header contains a pointer to the actual metadata, which may be stored in multiple segments scattered across the file. The header itself is a small, fixed size superblock containing version, magic number, and the offset/length of the first metadata segment.

**Dead Overwrite:** The superblock (e.g., first 512 bytes) never moves. The metadata tree is stored as a separate “file” managed by the same segment allocator used for user files.	When metadata grows, it can be extended using the same dead segment reuse and append logic.

**Pros**
- No arbitrary limits; metadata can grow indefinitely.
- Consistent with the rest of the filesystem design.
- Teaches the concept of a self hosted filesystem (the metadata is just another file).

**Cons**
- Significantly more complex to implement correctly.
- Bootstrapping problem: you need the metadata to find the metadata. 

### 10.4 Summary Table: Metadata Storage Trade Offs
---
Approach |	Space | Efficiency |	Complexity |	Risk of Data | Shift |
-|-|-|-|-|-
Unbounded | JSON | header |	Poor |	Low |	High (on every header growth) |
A) Reserved  | fixed | header |	Fair |	Low |	None |
B) Binary  | serialization |	Excellent |	Med |	Low | (if header fixed) |
C) Relocatable  | metadata | segments |	Excellent |	High |	None |

### 10.5 Recommendation:
---

For the scope of Lab 11, Option B (Binary serialization) combined with a reasonable size limit (e.g., 1 MB) provides the best balance between compression and preventing header data collision. The space overhead is negligible on modern systems, and the constraint is clearly documented.


# MULTI-USER CONCURRENT FILESYSTEM
<!-- documentation for next lab to add later -->

## 

## 