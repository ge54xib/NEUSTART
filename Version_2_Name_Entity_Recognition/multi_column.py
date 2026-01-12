import sys
import fitz

def column_boxes(page, footer_margin=50, header_margin=50, no_image_text=True):
    """
    Determine bboxes which wrap a column.
    
    Simplified to focus on:
    - Identifying text blocks.
    - Grouping them into vertical columns.
    - Returning integer coordinates sorted by top, then left.
    """
    bboxes = []
    
    # image bboxes (used to avoid processing text inside images if requested)
    img_bboxes = []

    # bboxes of non-horizontal text (used to avoid overlaps during extension)
    vert_bboxes = []

    # compute relevant page area
    clip = +page.rect
    clip.y1 -= footer_margin  # Remove footer area
    clip.y0 += header_margin  # Remove header area

    def can_extend(temp, bb, bboxlist):
        """
        Determines whether rectangle 'temp' can be extended by 'bb'
        without intersecting any of the rectangles contained in 'bboxlist'.
        """
        for b in bboxlist:
            if not intersects_bboxes(temp, vert_bboxes) and (
                b is None or b == bb or (temp & b).is_empty
            ):
                continue
            return False
        return True

    def in_bbox(bb, bboxes):
        """Return True if a bbox contains bb."""
        for bbox in bboxes:
            if bb in bbox:
                return True
        return False

    def intersects_bboxes(bb, bboxes):
        """Return True if a bbox intersects bb, else return False."""
        for bbox in bboxes:
            if not (bb & bbox).is_empty:
                return True
        return False

    def extend_right(bboxes, width, vert_bboxes, img_bboxes):
        """
        Extend a bbox to the right page border to create a full column width,
        stopping if it hits other text or images.
        """
        for i, bb in enumerate(bboxes):
            # do not extend text in images
            if in_bbox(bb, img_bboxes):
                continue

            # temp extends bb to the right page border
            temp = +bb
            temp.x1 = width

            # do not cut through images or vertical text
            if intersects_bboxes(temp, vert_bboxes + img_bboxes):
                continue

            # also, do not intersect other text bboxes
            check = can_extend(temp, bb, bboxes)
            if check:
                bboxes[i] = temp  # replace with enlarged bbox

        return [b for b in bboxes if b is not None]

    def clean_nblocks(nblocks):
        """Do some elementary cleaning (remove duplicates, sort segments)."""
        
        # 1. remove any duplicate blocks.
        blen = len(nblocks)
        if blen < 2:
            return nblocks
        start = blen - 1
        for i in range(start, -1, -1):
            bb1 = nblocks[i]
            bb0 = nblocks[i - 1]
            if bb0 == bb1:
                del nblocks[i]

        # 2. repair sequence: consecutive bboxes with almost same bottom value 
        # are sorted ascending by x-coordinate.
        y1 = nblocks[0].y1
        i0 = 0
        i1 = -1

        for i in range(1, len(nblocks)):
            b1 = nblocks[i]
            if abs(b1.y1 - y1) > 10:  # different bottom
                if i1 > i0:  # segment length > 1? Sort it!
                    nblocks[i0 : i1 + 1] = sorted(
                        nblocks[i0 : i1 + 1], key=lambda b: b.x0
                    )
                y1 = b1.y1
                i0 = i
            i1 = i
        if i1 > i0:
            nblocks[i0 : i1 + 1] = sorted(nblocks[i0 : i1 + 1], key=lambda b: b.x0)
        return nblocks

    # --------------------------------------------------------------------
    # 1. Identify Content
    # --------------------------------------------------------------------
    
    # bboxes of images on page (to avoid overlapping)
    for item in page.get_images():
        img_bboxes.extend(page.get_image_rects(item[0]))

    # blocks of text on page
    blocks = page.get_text(
        "dict",
        flags=fitz.TEXTFLAGS_TEXT,
        clip=clip,
    )["blocks"]

    # Make block rectangles, ignoring non-horizontal text
    for b in blocks:
        bbox = fitz.IRect(b["bbox"])  # bbox of the block

        # ignore text written upon images (optional safety)
        if no_image_text and in_bbox(bbox, img_bboxes):
            continue

        # confirm first line to be horizontal
        try:
            line0 = b["lines"][0]
            if line0["dir"] != (1, 0):
                vert_bboxes.append(bbox)
                continue
        except IndexError:
            continue

        # Build precise bbox from lines
        srect = fitz.EMPTY_IRECT()
        for line in b["lines"]:
            lbbox = fitz.IRect(line["bbox"])
            text = "".join([s["text"].strip() for s in line["spans"]])
            if len(text) > 1:
                srect |= lbbox
        bbox = +srect

        if not bbox.is_empty:
            bboxes.append(bbox)

    # Sort text bboxes by ascending top, then left coordinates
    # (Removed the background color sort key)
    bboxes.sort(key=lambda k: (k.y0, k.x0))

    # Extend bboxes to the right where possible
    bboxes = extend_right(
        bboxes, int(page.rect.width), vert_bboxes, img_bboxes
    )

    if not bboxes:
        return []

    # --------------------------------------------------------------------
    # 2. Join bboxes to establish column structure
    # --------------------------------------------------------------------
    nblocks = [bboxes[0]]  # pre-fill with first bbox
    bboxes = bboxes[1:]    # remaining old bboxes

    for i, bb in enumerate(bboxes):
        check = False

        # check if bb can extend one of the new blocks
        for j in range(len(nblocks)):
            nbb = nblocks[j]

            # never join across columns (if x-coordinates don't overlap)
            if bb is None or nbb.x1 < bb.x0 or bb.x1 < nbb.x0:
                continue
            
            # (Removed the background color check here)

            temp = bb | nbb  # temporary extension of new block
            check = can_extend(temp, nbb, nblocks)
            if check:
                break

        if not check:
            nblocks.append(bb)
            j = len(nblocks) - 1
            temp = nblocks[j]

        # check if some remaining bbox is contained in temp
        check = can_extend(temp, bb, bboxes)
        if not check:
            nblocks.append(bb)
        else:
            nblocks[j] = temp
        bboxes[i] = None

    # do some elementary cleaning
    nblocks = clean_nblocks(nblocks)

    return nblocks


if __name__ == "__main__":
    # Simple CLI for testing
    if len(sys.argv) < 2:
        print("Usage: python multi_column.py input.pdf [footer_margin] [header_margin]")
        sys.exit(1)

    filename = sys.argv[1]
    footer_margin = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    header_margin = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    doc = fitz.open(filename)
    for page in doc:
        page.wrap_contents()
        bboxes = column_boxes(page, footer_margin=footer_margin, header_margin=header_margin)
        
        # Draw for visual verification
        shape = page.new_shape()
        for i, rect in enumerate(bboxes):
            shape.draw_rect(rect)
            shape.insert_text(rect.tl + (5, 15), str(i), color=fitz.pdfcolor["red"])
        shape.finish(color=fitz.pdfcolor["red"])
        shape.commit()

    doc.ez_save(filename.replace(".pdf", "-blocks.pdf"))