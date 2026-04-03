using BillingGrpc;
using Grpc.Core;

namespace Patient_Management_System.Services
{
    public class BillingGrpcService(ILogger<BillingGrpcService> logger, BillingAccountService billingAccountService) : BillingService.BillingServiceBase
    {
        private readonly ILogger<BillingGrpcService> _logger = logger;
        private readonly BillingAccountService _billingAccountService = billingAccountService;
        public override async Task<BillingResponse> CreateBillingAccount(BillingRequest request, ServerCallContext context)
        {
            _logger.LogInformation("Billing request received for PatientId {PatientId}", request.PatientId);

            try
            {
                var billing = await _billingAccountService.CreateAccountAsync(request.PatientId);

                return new BillingResponse
                {
                    AccountId = billing.AccountId,
                    Status = billing.Status
                };
            }
            catch (Exception ex)
            {
                throw new RpcException(new Status(StatusCode.Internal, ex.Message));
            }
        }
    }
}   