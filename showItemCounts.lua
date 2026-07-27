local component = require("component")
local term = require("term")
local event = require("event")
local gpu = component.gpu

local internet = require("internet")
local pushUrl = "http://vpn.stevegame.de:8000/api/rs"

local rs = component.block_refinedstorage_interface
local refresh = 3

local capacity = 4 * 8 * 64000

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

local function jsonEscape(s)
  s = tostring(s or "")
  s = s:gsub("\\", "\\\\")
  s = s:gsub('"', '\\"')
  s = s:gsub("\n", "\\n")
  s = s:gsub("\r", "\\r")
  return s
end

local function pushItems(items, total)
  local parts = {}

  parts[#parts + 1] = '{"total":' .. math.floor(total) .. ',"items":['

  for i = 1, #items do
    local stack = items[i]
    if i > 1 then
      parts[#parts + 1] = ","
    end

    parts[#parts + 1] =
      '{"name":"' .. jsonEscape(stack.name) ..
      '","label":"' .. jsonEscape(stack.label or stack.name) ..
      '","size":' .. math.floor(tonumber(stack.size) or 0) ..
      '}'
  end

  parts[#parts + 1] = "]}"

  local body = table.concat(parts)

  local ok, req = pcall(
    internet.request,
    pushUrl,
    body,
    {["Content-Type"] = "application/json"},
    "POST"
  )

  if ok and req then
    for _ in req do break end
  end
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

  pushItems(items, total)

  local w, h = gpu.getResolution()
  term.clear()

  local header = ("Top RS items - Used: %s / %s items (%.1f%%)")
    :format(fmt(total), fmt(capacity), (total / capacity) * 100)
  gpu.set(1, 1, header:sub(1, w))

  local colWidth = math.floor(w / 2)
  local rowsPerCol = h - 1
  local numWidth = 8
  local nameWidth = colWidth - numWidth - 6

  for i = 1, math.min(#items, rowsPerCol * 2) do
    local stack = items[i]
    local name = stack.label or stack.name or "unknown"
    local count = fmt(stack.size)

    local col = math.floor((i - 1) / rowsPerCol)
    local row = ((i - 1) % rowsPerCol) + 2
    local x = col * colWidth + 1

    if #name > nameWidth then
      name = name:sub(1, nameWidth - 1) .. "…"
    end

    local text = string.format("%2d. %-"
      .. nameWidth .. "s %" .. numWidth .. "s", i, name, count)

    gpu.set(x, row, text:sub(1, colWidth - 1))
  end

  event.pull(refresh)
end