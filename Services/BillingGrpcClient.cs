using BillingGrpc;
using Grpc.Net.Client;

namespace Patient_Management_System.Services
{
    public class BillingGrpcClient
    {
        private readonly BillingService.BillingServiceClient _client;
        private readonly ILogger<BillingGrpcClient> _logger;

        public BillingGrpcClient(IConfiguration configuration, ILogger<BillingGrpcClient> logger)
        {
            _logger = logger;

            var address = configuration["BillingService:Address"] ?? "localhost";
            var port = configuration["BillingService:Port"] ?? "9001";

            var grpcUrl = $"http://{address}:{port}";

            _logger.LogInformation("Connecting to Billing Service at {GrpcUrl}", grpcUrl);

            var channel = GrpcChannel.ForAddress(grpcUrl);

            _client = new BillingService.BillingServiceClient(channel);
        }

        public async Task<BillingResponse> CreateBillingAccountAsync(int patientId)
        {
            var request = new BillingRequest
            {
                PatientId = patientId
            };

            var response = await _client.CreateBillingAccountAsync(request);

            _logger.LogInformation("Billing account created with ID {AccountId}", response.AccountId);

            return response;
        }
    }
}