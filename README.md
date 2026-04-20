CS330: Operating Systems
Lab 11: File Management
System Design Document

# 1. Overview
This document describes the design decisions made for the file management system in Lab ## 11. The system simulates a virtual file system stored entirely within a single data file (filesystem.dat). The implementation uses a hybrid architecture that balances simplicity with realistic OS-level behavior.

# 2. Architecture: The Hybrid Approach
The core design uses a Hybrid approach that divides filesystem.dat into two logical regions:

Region	What It Contains	Technology Used
JSON Header	Directory tree, file metadata, byte offsets, segment maps	Python dict serialized as JSON
Separator	A fixed delimiter separating the two regions	String: "<<<DATA>>>"
Raw Data Section	Actual file contents at specific byte offsets	Binary/text bytes written directly

This means directory management uses Python's natural dict/JSON capabilities while actual file content sits at real byte offsets — giving us a meaningful memory map without the full complexity of a block-based file system.

# 3. Structure of filesystem.dat
## 3.1 Visual Layout
filesystem.dat

    ┌─────────────────────────────────────────────┐
    │  JSON HEADER                                │
    │  {                                          │
    │    "cwd": "/root",                          │
    │    "root": { ... directory tree ... },      │
    │    "total_data_bytes": 615                  │
    │  }                                          │
    ├─────────────────────────────────────────────┤
    │  <<<DATA>>>                                 │  ← separator
    ├─────────────────────────────────────────────┤
    │  [bytes of notes.txt seg 1: offset 0  ]     │
    │  [bytes of essay.txt:       offset 200]     │
    │  [bytes of readme.txt:      offset 400]     │
    │  [bytes of notes.txt seg 2: offset 600]     │
    └─────────────────────────────────────────────┘

## 3.2 JSON Header Schema
Each file entry in the JSON tree contains:

Field	Type	Description
type	string	"file" or "dir"
size	int	Total bytes of file content across all segments
segments	list	Ordered list of {offset, length} dicts pointing into raw data section
children	dict	(Directories only) Maps child names to their entries

Example file entry:
{
  "notes.txt": {
    "type": "file",
    "size": 215,
    "segments": [
      {"offset": 0,   "length": 200},
      {"offset": 600, "length": 15}
    ]
  }
}
# 4. Segmentation Design
## 4.1 Why Segments?
Files do not always fit in one contiguous region. Rather than reshuffling all bytes every time a file grows (which is O(n) overhead on every write), files are allowed to have multiple segments. Each segment is an independent contiguous chunk in the raw data section.

When a file overflows its current last segment, a new segment is appended at the end of the raw data section. No existing bytes are moved.

## 4.2 Segment Growth Strategy
Situation	Action
Write fits in last segment	Write in place, update length
Write overflows last segment	Allocate new segment at end of raw section, append overflow there
Truncate reduces size	Remove trailing segments, trim last remaining segment

# . Dead Space and Compaction
## 5.1 How Dead Space Arises
Two operations produce dead (orphaned) bytes in the raw data section:
- Delete — the JSON entry is removed but the raw bytes at the old offsets remain untouched.
- Move within file — the source bytes are zeroed/abandoned after being copied to the destination.

During a session, dead regions accumulate between live segments. This is intentional and mirrors real file system behavior (deleted files linger on disk until overwritten).
## 5.2 Compaction on Startup
Rather than managing a free list at runtime (which adds significant complexity), compaction is deferred to program startup:
- Step 1 — Load all live segments from the JSON tree into a flat list.
- Step 2 — Rewrite the raw data section with only live segments, packed contiguously.
- Step 3 — Update all segment offsets in the JSON to match the new positions.
- Step 4 — Save the cleaned filesystem.dat.

This means fragmentation is visible mid-session on the memory map (which is educational) but is always cleaned up at the start of each new session.
# 6. Memory Map Generation
## 6.1 The Problem with JSON Traversal Order
The JSON tree is organized by directory structure, not by byte offset. Traversing it directly does not guarantee offset-ordered output. For example, a file deep in a subdirectory might have a lower byte offset than a file in root.
## 6.2 Algorithm
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

## 6.3 Sample Memory Map Output
Offset	Length	Status	File
0	200	LIVE	/root/notes.txt  (seg 1)
200	200	DEAD	(deleted: essay.txt)
400	30	LIVE	/root/docs/readme.txt
430	170	DEAD	(move_within_file residue)
600	15	LIVE	/root/notes.txt  (seg 2)
615	—	FREE	(never written)

# 7. Function Behaviour Summary
Function	JSON Impact	Raw Data Impact
Create(fName)	Add entry, segments=[], size=0	None until first write
Delete(fName)	Remove entry from tree	Raw bytes orphaned (dead space)
Mkdir(dirName)	Add dir entry with empty children	None
chDir(dirName)	Update cwd pointer in JSON	None
Move(src, tgt)	Reassign entry under new dir	None — offsets unchanged
Open(fName, mode)	None	None — returns FileObject
Write (append)	Update size, add segment if overflow	Write at end of last segment or new segment
Write_at(pos, text)	Update size if grown	Overwrite at byte position; extend if past end
Read()	None	Read all segments in order, concatenate
Read(start, size)	None	Walk segments to start offset, read size bytes
Move_within_file	None	Read chunk, zero source, write_at destination
Truncate(maxSize)	Remove trailing segments, update size	Trailing segment bytes become dead space
Show Memory Map	Traverse tree → collect all segments	Sort by offset, infer dead regions by gap detection

# 8. Key Design Decisions & Rationale
Decision	Alternative Considered	Why This Choice
Hybrid JSON + raw bytes	Pure JSON (content in header)	Pure JSON felt like cheating for an OS course — no real byte simulation
Segmented files (multi-segment)	Reserved padding per file	Padding causes empty holes requiring a free list; segments avoid both reshuffling and free list complexity
Delete = JSON removal only	Immediate byte reclamation	Mirrors real OS behavior; runtime free list adds too much overhead
Compaction on startup	Runtime compaction / free list	One clean sweep per session is sufficient; free list merge logic is a rabbit hole
Sort + gap detection for memory map	Rely on JSON traversal order	JSON is organized by directory, not offset; sorting guarantees correct physical order
write_at = overwrite (not insert)	Insert and shift	Lab spec says may overwrite; insert would require shifting all subsequent bytes across segments

# 9. Recommended Project Structure
File	Responsibility
filesystem.dat	The single data file — JSON header + separator + raw bytes
fs_core.py	FileSystem class: load/save .dat, create, delete, mkdir, chdir, move, compaction, memory map
file_object.py	FileObject class: open, read, write, write_at, move_within_file, truncate, close
shell.py	CLI loop: parses user commands and calls fs_core / file_object methods
sample.dat	Pre-populated example filesystem for demonstration

Design decisions derived from brainstorming session — April 2026
# 10. Advanced Space Management: Dead Segment Reuse and Logical Order Preservation
The baseline design defers all dead space reclamation to a single startup compaction pass. While simple, this strategy can cause unnecessary fragmentation during long sessions and incurs a fixed I/O cost at every program launch. The following optional enhancements reduce both runtime fragmentation and the frequency of full compaction events.
Field	Description
offset	Starting byte position of the dead block
length	Size of the dead block in bytes
## 10.1 Dead Segment Table (Free Space Tracking)
Instead of ignoring dead space until the next startup, maintain an in memory dead segment table that records every orphaned byte range in the raw data section. 
It is persisted in filesystem.dat within the header. The table is populated whenever a file is deleted, truncated, or when a move_within_file operation abandons its source bytes.
## 10.2 Segment Placement Policy: Favour Logical Physical Coherence
When a new segment must be allocated (e.g., due to an overflow write or file creation with initial data), the allocator inspects the dead segment table and applies the following best fit with logical order bias heuristic: 
1.	Identify all dead segments large enough to hold the requested data.
2.	Filter candidates that lie at a physical offset before the offset of the file’s next logical segment (or after the previous logical segment).
## 3.	Choose the smallest suitable dead segment among those that preserve the logical order.
## 4.	If no suitable dead segment exists, append the new segment to the free space at the end of the raw data section.
This policy ensures that, whenever possible, the physical layout of segments mirrors the logical order of the file. The benefit is a reduction in the number of disk seeks during sequential reads, as fragments are more likely to be stored consecutively.
## 10.3 Threshold Based Compaction (On Demand Cleanup)
Dead segment reuse cannot eliminate all fragmentation. Two scenarios still degrade read performance:
- Scattered small dead segments that are too tiny to be reused (internal fragmentation).
- End of file modifications that do not trigger new allocations, causing the dead segment table to grow while the physical layout stagnates.
To address this, implement a condition based cleanup analogous to background defragmentation in modern file systems:
- Threshold Trigger: After every N allocation operations (or when the total dead space exceeds some threshold, say 20% of the raw data section size), initiate a background compaction.

- Compaction Process:
1.	Perform the same streaming copy described in Section ## 5.2, but only on the live segments.
2.	Update all JSON segment offsets to the new contiguous positions.
## 3.	Clear the dead segment table (all dead space is now converted to a single contiguous free region at the end of the file).
This lazy cleanup avoids the I/O penalty of compacting at every startup while still preventing the filesystem from degrading into a severely fragmented state over long running sessions.

# 11. Metadata Storage Scalability: JSON Overhead and Reserved Regions

## 11.1 The Problem: Unbounded Header Growth
The hybrid design stores the entire directory tree and file metadata as a single JSON object at the start of filesystem.dat. While simple and debuggable, this approach has two scalability limitations:
1.	Verbose Encoding: JSON stores field names as plain text (e.g., "segments" repeated thousands of times). For a filesystem containing 10,000 files, the metadata header alone could exceed several megabytes, even though the actual information (names, offsets, sizes) is only a few hundred kilobytes.
2.	Header Data Boundary Shifting: Every time a file is created, deleted, or renamed, the JSON header changes size. Because the raw data section immediately follows the header, any header expansion forces the entire raw data section to be rewritten—the very problem segmentation was meant to avoid.

## 11.2 Real World Precedent: Fixed Metadata Regions
Production file systems do not intermingle variable length metadata with file data in a single contiguous stream. Instead, they allocate a fixed, reserved region at the beginning (or at known intervals) of the storage device for metadata structures.
These reserved regions ensure that metadata can grow and shrink within its own boundary without ever colliding with file data.

## 11.3 Proposed Mitigations for the Lab Filesystem

A) Reserve a Fixed Header Space (Simplest)

Implementation
Define a maximum header size (e.g., 1 MB or 10 MB) during filesystem creation. The first N bytes of filesystem.dat are permanently reserved for the JSON header. The raw data section begins at offset HEADER_RESERVED_SIZE.

Handling Overflow
If the JSON header exceeds the reserved space, the system returns an error ("Filesystem metadata full; delete some files or increase reserved space.").

Pros
- Zero shifting of data section on header updates.
- Trivial to implement.
- Preserves JSON readability for debugging.

Cons
- Arbitrary limit on number of files.
- Wasted space if the reservation is too large.

B) Binary Serialization of Metadata (Space Efficient)

Implementation
Replace the JSON text header with a custom binary format using Python’s struct module or a library like pickle (with caution) or msgpack. Each metadata record becomes a fixed size or length prefixed binary entry.

Space Savings

A JSON entry like {"name":"notes.txt","size":1024,"segments":[...]} might occupy 80 bytes; a binary equivalent using fixed length name fields and packed integers can be under 30 bytes.

Pros

- Drastically reduces metadata size and growth.
- Eliminates field name redundancy.
- Still allows for a reserved header region but with far less wasted space.
Cons
- Loss of human readability (debugging requires a hex dump or a separate tool).
- Slightly more complex parsing logic.

C) Relocatable Metadata with Overflow Area (Most Realistic but Complex)

Implementation
The header contains a pointer to the actual metadata, which may be stored in multiple segments scattered across the file. The header itself is a small, fixed size superblock containing version, magic number, and the offset/length of the first metadata segment.

Workflow
1.	The superblock (e.g., first 512 bytes) never moves.
2.	The metadata tree is stored as a separate “file” managed by the same segment allocator used for user files.
## 3.	When metadata grows, it can be extended using the same dead segment reuse and append logic.
Pros
- No arbitrary limits; metadata can grow indefinitely.
- Consistent with the rest of the filesystem design.
- Teaches the concept of a self hosted filesystem (the metadata is just another file).

Cons
- Significantly more complex to implement correctly.
- Bootstrapping problem: you need the metadata to find the metadata. 
## 11.4 Summary Table: Metadata Storage Trade Offs
Approach	Space Efficiency	Complexity	Risk of Data Shift
Unbounded JSON header	Poor	Low	High (on every header growth)

A) Reserved fixed header	Fair	Low	None

B) Binary serialization	Excellent	Med	Low (if header fixed)

C) Relocatable metadata segments	Excellent	High	None

## 11.5 Recommendation:

For the scope of Lab 11, Option B (Binary serialization) combined with a reasonable size limit (e.g., 1 MB) provides the best balance between compression and preventing header data collision. The space overhead is negligible on modern systems, and the constraint is clearly documented.