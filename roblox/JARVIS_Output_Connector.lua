-- Plugin opcional do JARVIS. Encaminha somente erros e avisos enquanto a captura estiver ligada.
local HttpService = game:GetService("HttpService")
local LogService = game:GetService("LogService")

local toolbar = plugin:CreateToolbar("JARVIS")
local button = toolbar:CreateButton(
	"CaptureOutput",
	"Ativar/desativar envio de erros e avisos do Output ao JARVIS local",
	""
)
button.ClickableWhenViewportHidden = true

local endpoint = "http://127.0.0.1:18743/roblox/output"
local active = false
local connection = nil

local function forward(entry)
	local kind = entry.messageType
	local level = nil
	if kind == Enum.MessageType.MessageError then
		level = "error"
	elseif kind == Enum.MessageType.MessageWarning then
		level = "warning"
	end
	if not level then
		return
	end

	local payload = {
		level = level,
		message = tostring(entry.message or ""),
		context = tostring(entry.context or ""),
	}
	task.spawn(function()
		pcall(function()
			HttpService:RequestAsync({
				Url = endpoint,
				Method = "POST",
				Headers = { ["Content-Type"] = "application/json" },
				Body = HttpService:JSONEncode(payload),
			})
		end)
	end)
end

button.Click:Connect(function()
	active = not active
	button:SetActive(active)
	if active then
		-- Lê o histórico atual ao ligar e continua acompanhando novas mensagens.
		local ok, history = pcall(function()
			return LogService:GetLogHistory()
		end)
		if ok then
			for _, entry in ipairs(history) do
				forward(entry)
			end
		end
		connection = LogService.MessageOut:Connect(function(message, messageType, context)
			forward({ message = message, messageType = messageType, context = context })
		end)
	else
		if connection then
			connection:Disconnect()
			connection = nil
		end
	end
end)
