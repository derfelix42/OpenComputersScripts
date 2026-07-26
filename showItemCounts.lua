local component = require("component")
local term = require("term")
local event = require("event")
local gpu = component.gpu

local rs = component.block_refinedstorage_interface
local refresh = 3

gpu.setResolution(80, 25)

local function fmt(n)
  local s = tostring(n):gsub("%.0$", "")
  while true do
    local k
    s, k = s:gsub("^(-?%d+)(%d%d%d)", "%1,%2")
    if k == 0 then break end
  end
  return s
end

while true do
  local items = rs.getItems()

  table.sort(items, function(a, b)
    return a.size > b.size
  end)

  local total = 0
  for i = 1, #items do
    total = total + items[i].size
  end

  local w, h = gpu.getResolution()
  term.clear()

  gpu.set(1, 1, ("Top RS items - Total items: %s"):format(fmt(total)):sub(1, w))

  local colWidth = math.floor(w / 2)
  local rowsPerCol = h - 1

  for i = 1, math.min(#items, rowsPerCol * 2) do
    local stack = items[i]
    local name = stack.label or stack.name or "unknown"

    local col = math.floor((i - 1) / rowsPerCol)
    local row = ((i - 1) % rowsPerCol) + 2
    local x = col * colWidth + 1

    local text = string.format("%2d. %s: %s", i, name, fmt(stack.size))
    gpu.set(x, row, text:sub(1, colWidth - 1))
  end

  event.pull(refresh)
end